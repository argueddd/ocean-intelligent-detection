import React, { useState } from 'react';
import styled from 'styled-components';
import { motion } from 'framer-motion';
// import { projectConfig } from '../data/projectConfig';

const MainDisplayContainer = styled.div`
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;

  @media (max-width: 1400px) {
    flex: 1.2;
  }

  @media (max-width: 1200px) {
    order: -1;
    min-height: clamp(250px, 30vh, 400px);
    flex: none;
  }

  @media (max-width: 768px) {
    min-height: clamp(200px, 25vh, 300px);
  }
`;

const VideoContainer = styled.div`
  width: 100%;
  max-width: clamp(600px, 50vw, 900px);
  position: relative;
`;

const VideoPlaceholder = styled(motion.div)`
  width: 100%;
  height: clamp(400px, 50vh, 800px);
  background: 
    radial-gradient(circle at center, rgba(0, 150, 255, 0.03) 0%, transparent 70%),
    linear-gradient(145deg, rgba(0, 0, 0, 0.85), rgba(10, 20, 40, 0.75));
  border: 1px solid rgba(0, 150, 255, 0.2);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  box-shadow: 
    0 4px 20px rgba(0, 0, 0, 0.4),
    0 0 20px rgba(0, 150, 255, 0.05);
  overflow: hidden;

  /* 科技感背景纹饰 */
  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background-image: 
      /* 对角线网格 */
      linear-gradient(45deg, rgba(0, 150, 255, 0.03) 25%, transparent 25%),
      linear-gradient(-45deg, rgba(0, 150, 255, 0.03) 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, rgba(0, 150, 255, 0.03) 75%),
      linear-gradient(-45deg, transparent 75%, rgba(0, 150, 255, 0.03) 75%);
    background-size: 40px 40px;
    background-position: 0 0, 0 20px, 20px -20px, -20px 0px;
    opacity: 0.6;
    z-index: 0;
  }

  &::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(0, 170, 255, 0.15) 0%, rgba(0, 170, 255, 0.05) 30%, transparent 70%);
    border-radius: 50%;
    z-index: 0;
    animation: pulseGlow 3s ease-in-out infinite;
    transform: translate(-50%, -50%);
  }

  @keyframes pulseGlow {
    0%, 100% { 
      transform: translate(-50%, -50%) scale(1);
      opacity: 0.4;
    }
    50% { 
      transform: translate(-50%, -50%) scale(1.2);
      opacity: 0.8;
    }
  }
`;

const VideoContent = styled.div`
  text-align: center;
  z-index: 10;
  position: relative;
`;

const ProjectNumber = styled(motion.div)`
  font-size: 150px;
  font-weight: 700;
  color: #ffffff;
  font-family: 'Source Code Pro', 'Monaco', 'Consolas', monospace;
  margin-bottom: 20px;
  position: relative;
  text-shadow: 0 0 30px rgba(0, 170, 255, 0.5);

  @media (max-width: 768px) {
    font-size: 100px;
  }
`;

const ProjectSubtitle = styled(motion.div)`
  font-size: 28px;
  color: #00aaff;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  text-shadow: 0 0 12px rgba(0, 170, 255, 0.4);
  margin-bottom: 10px;
`;

const ProjectDescription = styled(motion.div)`
  font-size: 18px;
  color: #cccccc;
  text-align: center;
  margin: 20px 0;
  max-width: 500px;
  line-height: 1.6;
  font-family: 'Inter', sans-serif;
`;

const FeaturesContainer = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin: 20px 0;
  max-width: 500px;
`;

const FeatureTag = styled(motion.span)`
  padding: 8px 16px;
  background: rgba(0, 150, 255, 0.08);
  border: 1px solid rgba(0, 150, 255, 0.2);
  border-radius: 20px;
  font-size: 14px;
  color: #00aaff;
  font-family: 'Inter', sans-serif;
  font-weight: 500;
`;

const ButtonContainer = styled.div`
  display: flex;
  gap: 20px;
  margin-top: 30px;
  align-items: center;
  justify-content: center;
`;

const PlayButton = styled(motion.button)`
  position: relative;
  padding: 12px 24px;
  background: linear-gradient(45deg, #ff6b6b, #ffa500);
  border: 1px solid rgba(255, 107, 107, 0.3);
  border-radius: 20px;
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 
    0 2px 8px rgba(0, 0, 0, 0.2),
    0 0 15px rgba(255, 107, 107, 0.2);
  display: flex;
  align-items: center;
  gap: 6px;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 
      0 4px 12px rgba(0, 0, 0, 0.3),
      0 0 20px rgba(255, 107, 107, 0.3);
    background: linear-gradient(45deg, #ff7b7b, #ffb500);
  }

  &:active {
    transform: translateY(0);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  }

  &::before {
    content: '▶';
    font-size: 12px;
  }
`;

const DemoButton = styled(motion.button)`
  position: relative;
  padding: 12px 24px;
  background: linear-gradient(45deg, #00aaff, #00ffaa);
  border: 1px solid rgba(0, 170, 255, 0.3);
  border-radius: 20px;
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 
    0 2px 8px rgba(0, 0, 0, 0.2),
    0 0 15px rgba(0, 170, 255, 0.2);
  display: flex;
  align-items: center;
  gap: 6px;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 
      0 4px 12px rgba(0, 0, 0, 0.3),
      0 0 20px rgba(0, 170, 255, 0.3);
    background: linear-gradient(45deg, #00bbff, #00ffbb);
  }

  &:active {
    transform: translateY(0);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  }

  &::before {
    content: '→';
    font-size: 14px;
  }
`;

const MainDisplay = ({ project, projectIndex, onDemoClick, isTransitioning }) => {
  const [showVideo, setShowVideo] = useState(false);
  const projectNumber = String(projectIndex + 1).padStart(2, '0');
  
  const handlePlayVideo = () => {
    setShowVideo(true);
  };

  const handleCloseVideo = () => {
    setShowVideo(false);
  };

  return (
    <MainDisplayContainer>
      <VideoContainer>
        <VideoPlaceholder
          key={projectIndex}
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.5 }}
        >
          <VideoContent>
            <ProjectNumber
              key={projectNumber}
              initial={{ scale: 0, rotate: -180 }}
              animate={{ scale: 1, rotate: 0 }}
              transition={{ 
                duration: 0.6, 
                type: "spring", 
                stiffness: 200,
                damping: 15
              }}
            >
              {projectNumber}
            </ProjectNumber>
            <ProjectSubtitle
              key={project.basicInfo.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.2 }}
            >
              {project.basicInfo.subtitle}
            </ProjectSubtitle>
            
            <ProjectDescription
              key={`desc-${projectIndex}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.4 }}
            >
              {project.basicInfo.description}
            </ProjectDescription>

            <FeaturesContainer>
              {project.basicInfo.features.slice(0, 4).map((feature, index) => (
                <FeatureTag
                  key={`${projectIndex}-${index}`}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.3, delay: 0.6 + index * 0.1 }}
                >
                  {feature}
                </FeatureTag>
              ))}
            </FeaturesContainer>
          </VideoContent>
        </VideoPlaceholder>
        <ButtonContainer>
          <PlayButton
            onClick={handlePlayVideo}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.8 }}
          >
            Play Demo
          </PlayButton>
          <DemoButton
            onClick={onDemoClick}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.9 }}
          >
            Go to Demo
          </DemoButton>
        </ButtonContainer>
      </VideoContainer>

      {/* 视频播放器 */}
      {showVideo && (
        <VideoModal onClick={handleCloseVideo}>
          <VideoPlayer onClick={(e) => e.stopPropagation()}>
            <VideoCloseButton onClick={handleCloseVideo}>×</VideoCloseButton>
            <video
              src={project.media.videoPath}
              controls
              autoPlay
              style={{ width: '100%', height: 'auto' }}
            >
              您的浏览器不支持视频播放。
            </video>
          </VideoPlayer>
        </VideoModal>
      )}
    </MainDisplayContainer>
  );
};

// 视频播放器样式
const VideoModal = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(10px);
`;

const VideoPlayer = styled.div`
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
  background: rgba(0, 0, 0, 0.8);
  border-radius: 12px;
  padding: 20px;
  border: 1px solid rgba(0, 170, 255, 0.3);
`;

const VideoCloseButton = styled.button`
  position: absolute;
  top: 10px;
  right: 15px;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  color: #fff;
  font-size: 24px;
  font-weight: bold;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  z-index: 10001;

  &:hover {
    background: rgba(255, 255, 255, 0.2);
    transform: scale(1.1);
  }
`;

export default MainDisplay;
