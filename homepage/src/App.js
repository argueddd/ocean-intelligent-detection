import React, { useState, useEffect, useCallback } from 'react';
import styled, { createGlobalStyle } from 'styled-components';
// import { motion, AnimatePresence } from 'framer-motion';
import LeftPanel from './components/LeftPanel';
import MainDisplay from './components/MainDisplay';
import RightPanel from './components/RightPanel';
import BottomNavigation from './components/BottomNavigation';
import { projectConfig, projectConfig2, projectConfig3, projectConfig4, projectConfig5, projectConfig6, projectConfig7 } from './data/projectConfig';

const GlobalStyle = createGlobalStyle`
  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
    background: 
      radial-gradient(circle at 20% 80%, rgba(0, 150, 255, 0.03) 0%, transparent 50%),
      radial-gradient(circle at 80% 20%, rgba(0, 255, 150, 0.02) 0%, transparent 50%),
      linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #0f1419 100%);
    color: #e8e8e8;
    overflow: hidden;
    height: 100vh;
    position: relative;
  }

  /* 科技感背景网格 */
  body::before {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-image: 
      linear-gradient(rgba(0, 150, 255, 0.08) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0, 150, 255, 0.08) 1px, transparent 1px);
    background-size: 80px 80px;
    z-index: -2;
    opacity: 0.6;
  }




  /* 科技感扫描线效果 */
  .scan-line {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg,
      transparent 0%,
      rgba(0, 150, 255, 0.4) 30%,
      rgba(0, 255, 150, 0.6) 50%,
      rgba(0, 150, 255, 0.4) 70%,
      transparent 100%);
    animation: scanMove 8s ease-in-out infinite;
    z-index: 1000;
    opacity: 0.7;
    box-shadow: 0 0 10px rgba(0, 150, 255, 0.3);
  }

  @keyframes scanMove {
    0% {
      top: 0;
      opacity: 0;
    }
    15% {
      opacity: 0.7;
    }
    85% {
      opacity: 0.7;
    }
    100% {
      top: 100vh;
      opacity: 0;
    }
  }

`;

const Container = styled.div`
  display: flex;
  height: calc(100vh - 80px);
  gap: clamp(10px, 2vw, 30px);
  padding: clamp(10px, 2vw, 30px);
  max-width: 100vw;
  overflow-x: hidden;

  @media (max-width: 1400px) {
    gap: clamp(8px, 1.5vw, 20px);
    padding: clamp(8px, 1.5vw, 20px);
  }

  @media (max-width: 1200px) {
    flex-direction: column;
    height: auto;
    min-height: calc(100vh - 80px);
    gap: 15px;
    padding: 15px;
  }

  @media (max-width: 768px) {
    padding: 10px;
    gap: 10px;
  }

  @media (max-width: 480px) {
    padding: 8px;
    gap: 8px;
  }
`;

// 添加悬浮机器人按钮样式
const FloatingRobotButton = styled.button`  position: fixed;
  bottom: 100px;
  right: 30px;
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: linear-gradient(135deg, #00c6ff, #0072ff);
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(0, 114, 255, 0.5);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;

  &:hover {
    transform: scale(1.1);
    box-shadow: 0 6px 25px rgba(0, 114, 255, 0.7);
  }

  &::after {
//    content: "🤖";
    font-size: 28px;
  }

  @media (max-width: 768px) {
    width: 50px;
    height: 50px;
    bottom: 80px;
    right: 20px;
  }`;

// 添加聊天窗口遮罩层样式
const ChatOverlay = styled.div`  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(5px);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;`;

// 添加聊天窗口容器样式
const ChatWindow = styled.div`  width: 90%;
  max-width: 1200px;
  height: 80%;
  background: #1a1a2e;
  border-radius: 15px;
  overflow: hidden;
  box-shadow: 0 0 40px rgba(0, 114, 255, 0.6);
  border: 1px solid rgba(0, 150, 255, 0.3);
  position: relative;

  @media (max-width: 768px) {
    width: 95%;
    height: 85%;
  }`;

// 添加关闭按钮样式
const CloseButton = styled.button`  position: absolute;
  top: 15px;
  right: 15px;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #ff4d4d;
  border: none;
  color: white;
  font-weight: bold;
  cursor: pointer;
  z-index: 2001;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.3s;

  &:hover {
    background: #ff1a1a;
  }`;



function App() {
  const [currentProjectIndex, setCurrentProjectIndex] = useState(0);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [isChatOpen, setIsChatOpen] = useState(false); // 添加这行

  // 创建项目数组，包含所有配置的项目
  const projects = [projectConfig, projectConfig2, projectConfig3, projectConfig4, projectConfig5, projectConfig6, projectConfig7];
  const currentProject = projects[currentProjectIndex];

  const handleProjectChange = useCallback((index) => {
    if (index === currentProjectIndex) return;
    
    setIsTransitioning(true);
    setTimeout(() => {
      setCurrentProjectIndex(index);
      setIsTransitioning(false);
    }, 300);
  }, [currentProjectIndex]);

  const handleDemoClick = useCallback(() => {
    if (currentProject.demoUrl) {
      window.open(currentProject.demoUrl, '_blank');
    }
  }, [currentProject.demoUrl]);

  // 键盘导航
  useEffect(() => {
    const handleKeyPress = (e) => {
      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          if (currentProjectIndex > 0) {
            handleProjectChange(currentProjectIndex - 1);
          }
          break;
        case 'ArrowRight':
          e.preventDefault();
          if (currentProjectIndex < projects.length - 1) {
            handleProjectChange(currentProjectIndex + 1);
          }
          break;
        case 'Enter':
          e.preventDefault();
          handleDemoClick();
          break;
        default:
          break;
      }
    };

    document.addEventListener('keydown', handleKeyPress);
    return () => document.removeEventListener('keydown', handleKeyPress);
  }, [currentProjectIndex, handleDemoClick, handleProjectChange, projects.length]);

  // 打开聊天窗口
  const openChat = () => {
    setIsChatOpen(true);
  };

  // 关闭聊天窗口
  const closeChat = () => {
    setIsChatOpen(false);
  };

  return (
    <>
      <GlobalStyle />
      <div className="scan-line"></div>
      <Container>
        <LeftPanel 
          project={currentProject} 
          isTransitioning={isTransitioning}
        />
        <MainDisplay 
          project={currentProject}
          projectIndex={currentProjectIndex}
          onDemoClick={handleDemoClick}
          isTransitioning={isTransitioning}
        />
        <RightPanel 
          project={currentProject}
          isTransitioning={isTransitioning}
        />
      </Container>
      <BottomNavigation
        currentIndex={currentProjectIndex}
        totalProjects={projects.length}
        onProjectChange={handleProjectChange}
      />

      {/* 悬浮机器人按钮 */}
      <FloatingRobotButton onClick={openChat} aria-label="打开AI助手">
          <img
            src="/robot-icon.png"
            alt="AI助手"
            style={{
              width: '60px',
              height: '60px',
              borderRadius: '50%'
            }}
          />
      </FloatingRobotButton>

      {/* 聊天窗口弹窗 */}
      {isChatOpen && (
        <ChatOverlay>
          <ChatWindow>
            <CloseButton onClick={closeChat} aria-label="关闭聊天窗口">×</CloseButton>
            <iframe
              src="/dify/app/chatbot/auNVmzkiHn6XIOTZ"
              style={{ width: '100%', height: '100%', minHeight: '700px' }}
              frameBorder="0"
              allow="microphone"
              title="AI服务推荐助手"
            />
          </ChatWindow>
        </ChatOverlay>
      )}
    </>
  );
}

export default App;
