from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, redirect, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.middleware.proxy_fix import ProxyFix


load_dotenv()

CAS_NAMESPACE = "http://www.yale.edu/tp/cas"
DEFAULT_LOCAL_SECRET = "local-development-only-change-me"

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("portal-auth")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return "/"
    return value


@dataclass(frozen=True)
class CasIdentity:
    username: str
    attributes: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        identity = {
            "username": self.username,
            "uid": self.attributes.get("uid", self.username),
            "displayName": self.attributes.get("displayName", self.username),
        }
        for key in ("departmentId", "departmentName"):
            value = self.attributes.get(key)
            if value:
                identity[key] = value
        return identity


def _parse_cas_response(xml_text: str) -> CasIdentity:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("CAS 返回了无法解析的 XML") from exc

    namespace = {"cas": CAS_NAMESPACE}
    failure = root.find(".//cas:authenticationFailure", namespace)
    if failure is not None:
        message = (failure.text or "CAS Ticket 校验失败").strip()
        raise ValueError(message)

    username = root.findtext(".//cas:authenticationSuccess/cas:user", namespaces=namespace)
    if not username:
        raise ValueError("CAS 响应中缺少用户身份")

    attributes: dict[str, str] = {}
    attributes_node = root.find(".//cas:authenticationSuccess/cas:attributes", namespace)
    if attributes_node is not None:
        for child in attributes_node:
            key = child.tag.rsplit("}", 1)[-1]
            attributes[key] = (child.text or "").strip()

    return CasIdentity(username=username.strip(), attributes=attributes)


def create_app(
    config: dict[str, Any] | None = None,
    http_client: Any | None = None,
) -> Flask:
    app = Flask(__name__)
    portal_public_url = os.environ.get("PORTAL_PUBLIC_URL", "http://127.0.0.1:4173").rstrip("/")
    app.config.from_mapping(
        APP_ENV=os.environ.get("APP_ENV", "development"),
        APP_SECRET_KEY=os.environ.get("APP_SECRET_KEY", DEFAULT_LOCAL_SECRET),
        CAS_PUBLIC_URL=os.environ.get("CAS_PUBLIC_URL", "http://127.0.0.1:9000/cas").rstrip("/"),
        CAS_INTERNAL_URL=os.environ.get("CAS_INTERNAL_URL", "http://127.0.0.1:9000/cas").rstrip("/"),
        CAS_SERVICE_URL=os.environ.get(
            "CAS_SERVICE_URL", f"{portal_public_url}/api/auth/callback"
        ),
        PORTAL_PUBLIC_URL=portal_public_url,
        SESSION_COOKIE_NAME=os.environ.get("SESSION_COOKIE_NAME", "portal_session"),
        SESSION_COOKIE_SECURE=_env_bool("SESSION_COOKIE_SECURE", False),
        SESSION_COOKIE_DOMAIN=os.environ.get("SESSION_COOKIE_DOMAIN") or None,
        SESSION_TTL_SECONDS=int(os.environ.get("SESSION_TTL_SECONDS", "3600")),
        LOGIN_FLOW_TTL_SECONDS=int(os.environ.get("LOGIN_FLOW_TTL_SECONDS", "300")),
        TRUST_PROXY=_env_bool("TRUST_PROXY", False),
    )
    if config:
        app.config.update(config)

    if (
        app.config["APP_ENV"] == "production"
        and app.config["APP_SECRET_KEY"] == DEFAULT_LOCAL_SECRET
    ):
        raise RuntimeError("生产环境必须配置随机 APP_SECRET_KEY")

    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    session_serializer = URLSafeTimedSerializer(
        app.config["APP_SECRET_KEY"], salt="agent-showcase-portal-session"
    )
    flow_serializer = URLSafeTimedSerializer(
        app.config["APP_SECRET_KEY"], salt="agent-showcase-portal-login-flow"
    )
    client = http_client or requests.Session()

    session_cookie_name = app.config["SESSION_COOKIE_NAME"]
    login_flow_cookie_name = "portal_login_flow"

    def cookie_options(max_age: int) -> dict[str, Any]:
        return {
            "max_age": max_age,
            "httponly": True,
            "secure": app.config["SESSION_COOKIE_SECURE"],
            "samesite": "Lax",
            "domain": app.config["SESSION_COOKIE_DOMAIN"],
            "path": "/",
        }

    def current_user() -> dict[str, Any] | None:
        signed_value = request.cookies.get(session_cookie_name)
        if not signed_value:
            return None
        try:
            user = session_serializer.loads(
                signed_value, max_age=app.config["SESSION_TTL_SECONDS"]
            )
        except (BadSignature, SignatureExpired):
            return None
        if not isinstance(user, dict) or not user.get("username"):
            return None
        return user

    def validate_ticket(ticket: str) -> CasIdentity:
        response = client.get(
            f"{app.config['CAS_INTERNAL_URL']}/serviceValidate",
            params={
                "service": app.config["CAS_SERVICE_URL"],
                "ticket": ticket,
            },
            timeout=5,
        )
        response.raise_for_status()
        return _parse_cas_response(response.text)

    @app.after_request
    def add_security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/api/auth/login")
    def login():
        return_to = _safe_return_to(request.args.get("return_to"))
        if current_user():
            return redirect(return_to, 302)

        flow_token = flow_serializer.dumps({"return_to": return_to})
        cas_login_url = f"{app.config['CAS_PUBLIC_URL']}/login?{urlencode({'service': app.config['CAS_SERVICE_URL']})}"
        response = make_response(redirect(cas_login_url, 302))
        response.set_cookie(
            login_flow_cookie_name,
            flow_token,
            **cookie_options(app.config["LOGIN_FLOW_TTL_SECONDS"]),
        )
        return response

    @app.get("/api/auth/callback")
    def callback():
        flow_token = request.cookies.get(login_flow_cookie_name)
        try:
            flow = flow_serializer.loads(
                flow_token or "", max_age=app.config["LOGIN_FLOW_TTL_SECONDS"]
            )
        except (BadSignature, SignatureExpired):
            logger.warning("拒绝缺少有效登录流程 Cookie 的 CAS 回调")
            return redirect("/?auth_error=invalid_flow", 302)

        ticket = (request.args.get("ticket") or "").strip()
        if not ticket:
            return redirect("/?auth_error=missing_ticket", 302)

        try:
            identity = validate_ticket(ticket)
        except (requests.RequestException, ValueError):
            logger.exception("CAS 回调处理失败")
            return redirect("/?auth_error=validation_failed", 302)

        response = make_response(redirect(_safe_return_to(flow.get("return_to")), 302))
        response.delete_cookie(
            login_flow_cookie_name,
            path="/",
            domain=app.config["SESSION_COOKIE_DOMAIN"],
        )
        response.set_cookie(
            session_cookie_name,
            session_serializer.dumps(identity.as_dict()),
            **cookie_options(app.config["SESSION_TTL_SECONDS"]),
        )
        return response

    @app.get("/api/auth/me")
    def me():
        user = current_user()
        return jsonify({"authenticated": bool(user), "user": user})

    @app.post("/api/auth/logout")
    def logout():
        return_to = _safe_return_to(request.args.get("return_to"))
        portal_return_url = f"{app.config['PORTAL_PUBLIC_URL']}{return_to}"
        logout_url = f"{app.config['CAS_PUBLIC_URL']}/logout?{urlencode({'service': portal_return_url})}"
        response = jsonify({"logoutUrl": logout_url})
        response.delete_cookie(
            session_cookie_name,
            path="/",
            domain=app.config["SESSION_COOKIE_DOMAIN"],
        )
        return response

    @app.get("/api/auth/health")
    def health():
        return jsonify({"status": "ok"})

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "9010")), debug=False)
