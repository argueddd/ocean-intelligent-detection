# CA/OS 理论系数内核与验证边界

状态：cfar_theory 0.1.0，2026-10-05。已实现仅依赖 Python 标准库的系数数学函数与确定性测试；不是 CA/OS 信号检测器、算法登记或公共执行入口。使用前同时遵守 [CFAR 设计](cfar-design.md) 和 [门限设计](cfar-threshold-design.md)。

## 1. 本轮解决什么

给定显式的内部单元概率 p_cell、参考单元总数 N，以及 OS 的整数秩 k，计算理论系数 alpha，并返回反算对数概率与数值残差。也可由显式 alpha 反算理论 log(p_cell)。

用户已确认的控制口径是帧级/整段事件概率二选一，按输入信号与检测算法分别控制；它与本内核的单元概率不是同一层。q/M 均分已获确认并由 runtime v1 实现；本数学模块仍不做分配，不用 p_cell 冒充 q。函数参数没有实测默认值，测试数值不是建议参数。

不读取文件或信号，不计算 PSD/STFT、不决定参考区、不判定谱峰、不标定，不写 DetectionResult，不导出运行许可。后续调用方仍须核对来源、模型、实际参数和用户确认。不得因为函数能被调用就跳过这些边界。

## 2. 模型与数学定义

假设 CUT 与 N 个参考功率单元相互独立、同分布，均为共同均值的指数随机变量。只有在该模型下，下列 p 才有相应单元概率解释。数学验证不检验真实数据的分布；平均谱、频点相关、自适应波束及非同质背景不能自动满足模型。

CA 使用参考值均值，系数为 N × expm1(-log(p)/N)，反算为 -N × log1p(alpha/N)。不是参考总和的系数。公式和无积累限制依据 [MathWorks CFAR 教程](https://www.mathworks.com/help/phased/ug/constant-false-alarm-rate-cfar-detection.html)。

OS 使用升序第 k 项，1 起始；不是百分位插值或两项均值中位数。定义见 [MathWorks CFARDetector](https://www.mathworks.com/help/phased/ref/phased.cfardetector-system-object.html)。实现求解：

```text
log(p) = -sum(log1p(alpha/r)), r = N-k+1 ... N
```

这等价于 [Rohling 第 36 式](https://nato-us.org/sensors2005/papers/rohling.pdf) 的 Gamma/阶乘比。本实现的推导：把参考值按共同均值归一化后，第 k 顺序统计量是速率 N、N-1、…、N-k+1 的独立指数间距之和；对该和取 Laplace 变换，即得到各 r/(r+alpha) 的乘积。仅使用其模型公式，不照搬论文雷达参数。

## 3. 可调用函数

代码：[scripts/cfar_theory.py](../scripts/cfar_theory.py)。

| 函数 | 显式参数 | 返回 |
|---|---|---|
| ca_coefficient_iid_exponential | p_cell, n_reference | TheoryCoefficient |
| os_coefficient_iid_exponential | p_cell, n_reference, rank | TheoryCoefficient |
| ca_log_pfa_iid_exponential | alpha, n_reference | 理论单元概率的自然对数 |
| os_log_pfa_iid_exponential | alpha, n_reference, rank | 理论单元概率的自然对数 |

所有参数必填；函数名显式包含模型。只接受内置 Python int/float 数值，不把字符串、布尔、数组、百分位或浮点秩默默转换。p 须严格位于 (0,1)，N/k 须为整数，1 ≤ k ≤ N。反算函数允许 alpha=0，返回 log(p)=0；实际系数生成只返回正有限 alpha。

TheoryCoefficient 是不可变数学结果：包含方法、p、N、OS 秩或不适用、alpha、反算 log(p)、绝对/相对对数残差、求解迭代数、模型和实现版本以及容差。没有信号身份、实验真值、执行成功或工程通过声明；它不是公共结果 Schema 的替代品。

## 4. 版本化数值规则

- 使用 binary64 Python float，log1p/expm1 与 math.fsum；运行时检查浮点格式。
- N 上限 100000 是本实现的资源/数值边界，不是推荐参考区大小。数学函数允许奇数 N 或 N=1，并不意味着本版双侧参考区允许这些几何配置。
- OS 的 k=1 使用其自身闭式解 N × expm1(-log(p))；不是失败后退回 CA。
- k>1 使用单调二分。数学上界 N × expm1(-log(p)/k) 来自 sum(log1p(alpha/r)) ≥ k × log1p(alpha/N)；最多 128 次迭代。
- 反算 log(p) 的绝对误差须 ≤ 5e-13，且相对于 abs(log(p)) 的误差须 ≤ 2e-13，两项同时满足。这样既保护 p 接近 1 的情况，也避免极小 p 时只看相对对数残差过早停止。
- 系数溢出、非有限值、分项比值落入次正规范围、括区间/迭代/残差失败都显式报错，不裁剪、不加 epsilon、不换算法、不放宽 p。系数求解可接受可表示的次正规 p；若对应 alpha 不可表示则失败。反算 API 对次正规 alpha/参考数比值不承诺精度，拒绝继续。
- 返回值是指定容差下的近似数学根，不是向保守侧舍入的严格上界证明。后续概率预算器必须记录这个误差边界，不能把浮点结果宣称为无误差精确控制。

CFARParameterError 表示参数类型、范围或实现规模不支持；CFARNumericalError 表示数值结果无法可靠给出。失败不返回备用系数。

## 5. 已验证与未验证

测试：[tests/test_cfar_theory.py](../tests/test_cfar_theory.py)。使用确定性数学输入，不用海试数据、不生成 H0 随机实验：

- CA 与高精度 Decimal 公式及 N=1 闭式解对照，核对均值/总和区别。
- OS 与 k=1、N=2/k=2 的独立闭式解对照；用高精度乘积验证一般秩的反算关系。
- 常规、接近 1、极小及次正规概率，概率/秩单调关系，参数类型和越界。
- 不可表示系数、分项下溢、求解失败、残差失败不产生替代结果；输出不可变且带数值依据。
- 确认所有科学参数均无函数默认值。

在 Skill 根目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p test_cfar_theory.py -v
```

这些测试不证明实际水声背景模型成立、帧/段事件目标达到、候选正确或完成工程验收。这些功能现由 [runtime v1](runtime-v1.md) 与 [标定入口](calibration-v1.md) 另外实现；本数学模块及既有 preflight 的边界不变。

## 6. 与执行框架的关系

事件层次、q/M、H0 最大值、谱和候选规则已获确认；cfar_core/cfar_registry/detection_runtime 在核对模型与真实执行确认后复用本内核。数学内核不单独登记成完整检测器，不改原交接格式、既有预检权限或评价模块。
