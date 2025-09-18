import React, { useState, useEffect, useCallback } from 'react';
import styled, { createGlobalStyle } from 'styled-components';
// import { motion, AnimatePresence } from 'framer-motion';
import LeftPanel from './components/LeftPanel';
import MainDisplay from './components/MainDisplay';
import RightPanel from './components/RightPanel';
import BottomNavigation from './components/BottomNavigation';
import { projectConfig, projectConfig2, projectConfig3, projectConfig4 } from './data/projectConfig';

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

function App() {
  const [currentProjectIndex, setCurrentProjectIndex] = useState(0);
  const [isTransitioning, setIsTransitioning] = useState(false);

  // 创建项目数组，包含所有配置的项目
  const projects = [projectConfig, projectConfig2, projectConfig3, projectConfig4];
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
    </>
  );
}

export default App;
