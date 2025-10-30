import React, { useState, useEffect } from 'react';
import styled from 'styled-components';
import { motion } from 'framer-motion';
// import { projectConfig } from '../data/projectConfig';

const Panel = styled(motion.div)`
  flex: 0 0 clamp(280px, 25vw, 380px);
  background: 
    linear-gradient(145deg, rgba(0, 0, 0, 0.85), rgba(10, 20, 40, 0.75));
  border: 1px solid rgba(0, 150, 255, 0.2);
  border-radius: 12px;
  padding: clamp(16px, 2vw, 32px);
  backdrop-filter: blur(10px);
  box-shadow: 
    0 4px 20px rgba(0, 0, 0, 0.4),
    0 0 20px rgba(0, 150, 255, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  position: relative;
  min-height: 0;

  @media (max-width: 1400px) {
    flex: 0 0 clamp(260px, 28vw, 320px);
    padding: clamp(14px, 1.8vw, 24px);
  }

  @media (max-width: 1200px) {
    flex: none;
    width: 100%;
    padding: 20px;
  }

  @media (max-width: 768px) {
    padding: 16px;
  }

  @media (max-width: 480px) {
    padding: 12px;
  }
`;

const PanelContent = styled.div`
  height: 100%;
  display: flex;
  flex-direction: column;
`;

const ProjectTitle = styled(motion.h2)`
  font-size: 24px;
  color: #00aaff;
  margin-bottom: 32px;
  text-align: center;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 1px;
  text-shadow: 0 0 8px rgba(0, 170, 255, 0.3);
  position: relative;
  
  &::after {
    content: '';
    position: absolute;
    bottom: -8px;
    left: 50%;
    transform: translateX(-50%);
    width: 50px;
    height: 2px;
    background: linear-gradient(90deg, transparent, #00aaff, transparent);
    border-radius: 1px;
  }
`;

const ProgressSection = styled.div`
  margin-bottom: 32px;
`;

// 圆形进度条组件
const CircularProgressContainer = styled.div`
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin: 24px 0;
`;

const CircularProgress = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
`;

const ProgressCircle = styled.div`
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: conic-gradient(
    ${props => `#00aaff 0deg, #00aaff ${props.progress * 3.6}deg, rgba(0, 170, 255, 0.15) ${props.progress * 3.6}deg, rgba(0, 170, 255, 0.15) 360deg`}
  );
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  margin-bottom: 12px;
  box-shadow: 
    0 2px 8px rgba(0, 0, 0, 0.3),
    0 0 15px rgba(0, 170, 255, 0.2);

  &::before {
    content: '';
    position: absolute;
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.8);
    z-index: 1;
    border: 1px solid rgba(0, 170, 255, 0.2);
  }
`;

const ProgressValue = styled.div`
  position: absolute;
  z-index: 2;
  font-size: 16px;
  font-weight: 600;
  color: #ffffff;
  font-family: 'Source Code Pro', 'Monaco', 'Consolas', monospace;
`;

const CircularProgressLabel = styled.div`
  font-size: 14px;
  color: #cccccc;
  text-align: center;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
`;

// 智能体指标网格
const MetricsGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin: 20px 0;
`;

const MetricCard = styled.div`
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(0, 170, 255, 0.2);
  border-radius: 8px;
  padding: 12px;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(0, 170, 255, 0.05);
    border-color: rgba(0, 170, 255, 0.3);
    transform: translateY(-1px);
  }
`;

const MetricLabel = styled.div`
  font-size: 11px;
  color: #cccccc;
  margin-bottom: 4px;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

// 应用信息部分
const ApplicationInfoSection = styled.div`
  margin-bottom: 32px;
`;

const InfoGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin: 20px 0;
`;

const InfoCard = styled.div`
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(0, 255, 150, 0.2);
  border-radius: 8px;
  padding: 12px;
  text-align: center;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(0, 255, 150, 0.05);
    border-color: rgba(0, 255, 150, 0.3);
    transform: translateY(-1px);
  }
`;

const InfoLabel = styled.div`
  font-size: 11px;
  color: #cccccc;
  margin-bottom: 4px;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

const InfoValue = styled.div`
  font-size: 14px;
  font-weight: 600;
  color: ${props => {
    if (props.type === '流程类应用') return '#00aaff';
    if (props.type === '问答类应用') return '#00ffaa';
    if (props.type === '全自动应用') return '#ff6b6b';
    if (props.type === '低') return '#00ffaa';
    if (props.type === '中等') return '#ffa500';
    if (props.type === '高') return '#ff6b6b';
    return '#ffffff';
  }};
  font-family: 'Inter', sans-serif;
`;

// 项目基本信息
const ProjectInfoSection = styled.div`
  margin-bottom: 32px;
`;

const ProjectSubtitle = styled.div`
  font-size: 14px;
  color: #cccccc;
  text-align: center;
  margin-bottom: 16px;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 1px;
`;

const ProjectContact = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const ContactItem = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
`;

const ContactLabel = styled.div`
  font-size: 10px;
  color: #cccccc;
  font-family: 'Source Code Pro', monospace;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

const ContactValue = styled.div`
  font-size: 11px;
  color: #00aaff;
  font-family: 'Source Code Pro', monospace;
`;

// 技能评分
const SkillsSection = styled.div`
  margin-bottom: 32px;
`;

const SkillsList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

const SkillItem = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
`;

const SkillName = styled.div`
  font-size: 12px;
  color: #cccccc;
  font-family: 'Inter', sans-serif;
  flex: 1;
`;

const SkillProgress = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
`;

const SkillBar = styled.div`
  flex: 1;
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
`;

const SkillFill = styled.div`
  height: 100%;
  width: ${props => props.width};
  background: linear-gradient(90deg, #00aaff, #00ffaa);
  border-radius: 2px;
  transition: width 0.3s ease;
`;

const SkillScore = styled.div`
  font-size: 10px;
  color: #00aaff;
  font-family: 'Source Code Pro', monospace;
  min-width: 30px;
  text-align: right;
`;

// 技术熟练度
const TechProficiencySection = styled.div`
  margin-bottom: 32px;
`;

const TechGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
`;

const TechProficiencyCard = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
`;

const TechProficiencyCircle = styled.div`
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: conic-gradient(
    #00aaff 0deg,
    #00aaff ${props => props.progress * 3.6}deg,
    rgba(0, 170, 255, 0.15) ${props => props.progress * 3.6}deg,
    rgba(0, 170, 255, 0.15) 360deg
  );
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  margin-bottom: 6px;
  animation: fillProgress 2s ease-out forwards;
  animation-delay: ${props => props.index * 0.2}s;
  box-shadow: 0 0 15px rgba(0, 170, 255, 0.2);

  &::before {
    content: '';
    position: absolute;
    width: 35px;
    height: 35px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.8);
    z-index: 1;
  }

  &::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 6px;
    height: 6px;
    background: #00aaff;
    border-radius: 50%;
    transform: translate(-50%, -50%) rotate(0deg) translateY(-21px);
    z-index: 2;
    box-shadow: 0 0 8px rgba(0, 170, 255, 0.8);
    animation: progressIndicator 2s ease-out forwards;
    animation-delay: ${props => props.index * 0.3}s;
  }

  @keyframes fillProgress {
    0% {
      background: conic-gradient(
        rgba(0, 170, 255, 0.15) 0deg,
        rgba(0, 170, 255, 0.15) 360deg
      );
    }
    100% {
      background: conic-gradient(
        #00aaff 0deg,
        #00aaff ${props => props.progress * 3.6}deg,
        rgba(0, 170, 255, 0.15) ${props => props.progress * 3.6}deg,
        rgba(0, 170, 255, 0.15) 360deg
      );
      box-shadow: 0 0 20px rgba(0, 170, 255, 0.4);
    }
  }

  @keyframes progressIndicator {
    0% {
      transform: translate(-50%, -50%) rotate(0deg) translateY(-21px);
      opacity: 0;
    }
    50% {
      opacity: 1;
    }
    100% {
      transform: translate(-50%, -50%) rotate(${props => props.progress * 3.6}deg) translateY(-21px);
      opacity: 1;
    }
  }

  &:hover {
    box-shadow: 0 0 30px rgba(0, 170, 255, 0.6);
    transform: scale(1.05);
    transition: all 0.3s ease;
  }
`;

const TechProficiencyValue = styled.div`
  position: absolute;
  z-index: 2;
  font-size: 10px;
  font-weight: 600;
  color: #ffffff;
  font-family: 'Source Code Pro', monospace;
`;

const TechProficiencyLabel = styled.div`
  font-size: 9px;
  color: #cccccc;
  text-align: center;
  font-family: 'Inter', sans-serif;
`;


// 时间线
const TimelineSection = styled.div`
  margin-bottom: 32px;
`;

const TimelineContainer = styled.div`
  position: relative;
  padding-left: 16px;

  &::before {
    content: '';
    position: absolute;
    left: 6px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: rgba(0, 170, 255, 0.3);
  }
`;

const TimelineItem = styled.div`
  position: relative;
  margin-bottom: 16px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
`;

const TimelineDot = styled.div`
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #00aaff;
  border: 2px solid rgba(0, 0, 0, 0.8);
  position: absolute;
  left: -22px;
  top: 4px;
  z-index: 1;
`;

const TimelineContent = styled.div`
  flex: 1;
`;

const TimelineYear = styled.div`
  font-size: 10px;
  color: #00aaff;
  font-family: 'Source Code Pro', monospace;
  margin-bottom: 2px;
`;

const TimelineTitle = styled.div`
  font-size: 12px;
  color: #ffffff;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  margin-bottom: 4px;
`;

const TimelineDescription = styled.div`
  font-size: 10px;
  color: #cccccc;
  font-family: 'Inter', sans-serif;
  line-height: 1.4;
`;

// 分段式进度条
const SegmentedMetricsList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 16px;
`;

const SegmentedMetricItem = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
`;

const SegmentedBar = styled.div`
  display: flex;
  gap: 4px;
`;

const SegmentedBlock = styled.div`
  width: 12px;
  height: 12px;
  background: ${props => props.filled ? props.color : 'rgba(255, 255, 255, 0.1)'};
  border-radius: 2px;
  transition: all 0.3s ease;
`;

// 翻页卡片
const SkillCardContainer = styled.div`
  position: relative;
  height: 80px;
  perspective: 1000px;
`;

const FlipCard = styled.div`
  position: relative;
  width: 100%;
  height: 100%;
  transform-style: preserve-3d;
  transition: transform 0.6s ease;
  transform: ${props => props.isFlipped ? 'rotateY(180deg)' : 'rotateY(0deg)'};
  cursor: pointer;
`;

const CardFront = styled.div`
  position: absolute;
  width: 100%;
  height: 100%;
  backface-visibility: hidden;
  background: rgba(0, 170, 255, 0.05);
  border: 1px solid rgba(0, 170, 255, 0.2);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: center;
`;

const CardBack = styled.div`
  position: absolute;
  width: 100%;
  height: 100%;
  backface-visibility: hidden;
  background: rgba(0, 255, 150, 0.05);
  border: 1px solid rgba(0, 255, 150, 0.2);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  transform: rotateY(180deg);
`;

const CardTitle = styled.div`
  font-size: 14px;
  color: #00aaff;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  margin-bottom: 8px;
`;

const CardDescription = styled.div`
  font-size: 11px;
  color: #cccccc;
  font-family: 'Inter', sans-serif;
  line-height: 1.4;
`;

// 为CardBack中的文字单独定义样式
const CardBackTitle = styled.div`
  font-size: 14px;
  color: #00ff88;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  margin-bottom: 8px;
  text-shadow: 0 0 6px rgba(0, 255, 136, 0.3);
`;

const CardBackDescription = styled.div`
  font-size: 11px;
  color: #ffffff;
  font-family: 'Inter', sans-serif;
  line-height: 1.4;
`;

const SkillIndicators = styled.div`
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
`;

const Indicator = styled.div`
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: ${props => props.active ? '#00aaff' : 'rgba(255, 255, 255, 0.2)'};
  transition: all 0.3s ease;
`;

// 项目启动时间
const ProjectStartTime = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
  padding: 12px 16px;
  background: rgba(0, 170, 255, 0.05);
  border: 1px solid rgba(0, 170, 255, 0.2);
  border-radius: 8px;
`;

const StartTimeLabel = styled.div`
  font-size: 12px;
  color: #cccccc;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

const StartTimeValue = styled.div`
  font-size: 14px;
  color: #00aaff;
  font-weight: 600;
  font-family: 'Source Code Pro', monospace;
`;

// 智能体性能指标 - 紧凑卡片式
const PerformanceCardsGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
`;

// token消耗 - 紧凑卡片式
const TokenGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
`;

const PerformanceCard = styled(motion.div)`
  background: rgba(0, 170, 255, 0.05);
  border: 1px solid rgba(0, 170, 255, 0.2);
  border-radius: 6px;
  padding: 6px;
  text-align: center;
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;

  &:hover {
    background: rgba(0, 170, 255, 0.1);
    border-color: rgba(0, 170, 255, 0.4);
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(0, 170, 255, 0.2);
  }

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
    animation: cardShimmer 3s infinite;
  }

  @keyframes cardShimmer {
    0% { left: -100%; }
    100% { left: 100%; }
  }
`;

const PerformanceValue = styled.div`
  font-size: 13px;
  font-weight: 600;
  color: #00aaff;
  font-family: 'Source Code Pro', monospace;
  margin-bottom: 3px;
  text-shadow: 0 0 6px rgba(0, 170, 255, 0.3);
`;

const PerformanceLabel = styled.div`
  font-size: 9px;
  color: #cccccc;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.3px;
`;

// 酷炫维度评估
const CoolMetricsList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 16px;
`;

const CoolMetricItem = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
`;

const CoolProgressBar = styled.div`
  flex: 1;
  height: 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
  border: 1px solid rgba(255, 255, 255, 0.1);
`;

const CoolProgressFill = styled.div`
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, ${props => props.color}, ${props => props.color}dd);
  border-radius: 3px;
  animation: fillProgressBar 2s ease-out forwards;
  animation-delay: ${props => props.index * 0.2}s;
  position: relative;
  --target-width: ${props => props.width};
  
  &::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.4), transparent);
    animation: pulse 2s infinite;
  }
  
  @keyframes fillProgressBar {
    0% {
      width: 0%;
    }
    100% {
      width: var(--target-width);
    }
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 1; }
  }
`;

const CoolMetricValue = styled.div`
  font-size: 12px;
  font-weight: 600;
  color: #00aaff;
  font-family: 'Source Code Pro', monospace;
  min-width: 40px;
  text-align: right;
`;

const ProgressLabel = styled.div`
  font-size: 16px;
  margin-bottom: 20px;
  color: #00ffff;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  text-shadow: 0 0 6px rgba(0, 255, 255, 0.3);
`;

const ProgressBar = styled.div`
  width: 100%;
  height: 12px;
  background: 
    linear-gradient(90deg, 
      rgba(0, 0, 0, 0.8) 0%, 
      rgba(20, 20, 40, 0.6) 50%, 
      rgba(0, 0, 0, 0.8) 100%);
  border: 1px solid rgba(0, 255, 255, 0.3);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 5px;
  position: relative;
  box-shadow: 
    inset 0 0 10px rgba(0, 0, 0, 0.5),
    0 0 10px rgba(0, 255, 255, 0.2);

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(90deg, 
      transparent 0%, 
      rgba(0, 255, 255, 0.1) 50%, 
      transparent 100%);
    animation: progressScan 2s linear infinite;
  }

  @keyframes progressScan {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
  }
`;

const ProgressFill = styled(motion.div)`
  height: 100%;
  background: 
    linear-gradient(90deg, 
      #00ff88 0%, 
      #00ffff 25%, 
      #ff00ff 50%, 
      #ffff00 75%, 
      #00ff88 100%);
  background-size: 200% 100%;
  border-radius: 6px;
  box-shadow: 
    0 0 10px rgba(0, 255, 136, 0.8),
    0 0 20px rgba(0, 255, 255, 0.6),
    inset 0 0 10px rgba(255, 255, 255, 0.2);
  position: relative;
  animation: progressFlow 3s ease-in-out infinite;

  &::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(90deg, 
      transparent 0%, 
      rgba(255, 255, 255, 0.3) 50%, 
      transparent 100%);
    animation: progressShine 1.5s ease-in-out infinite;
  }

  @keyframes progressFlow {
    0%, 100% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
  }

  @keyframes progressShine {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
  }
`;

const ProgressText = styled(motion.div)`
  text-align: right;
  font-size: 14px;
  color: #00aaff;
  font-weight: bold;
`;


const AchievementsSection = styled.div`
  h3 {
    color: #00ffff;
    margin-bottom: 15px;
    font-size: 18px;
  }
`;

const AchievementsList = styled.ul`
  list-style: none;
`;

const AchievementItem = styled(motion.li)`
  padding: 8px 0;
  border-left: 3px solid #00ff88;
  padding-left: 15px;
  margin-bottom: 10px;
  background: rgba(0, 255, 136, 0.1);
  border-radius: 0 5px 5px 0;
  transition: all 0.3s ease;
  cursor: default;

  &:hover {
    background: rgba(0, 255, 136, 0.2);
    transform: translateX(5px);
  }
`;

// 新增样式组件
const ModulesSection = styled.div`
  margin-bottom: 20px;
  
  h3 {
    color: #00ffff;
    margin-bottom: 15px;
    font-size: 18px;
  }
`;

const ModulesList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 10px;
`;

const ModuleItem = styled(motion.div)`
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(0, 255, 255, 0.2);
  border-radius: 8px;
  padding: 12px;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(0, 255, 255, 0.4);
    transform: translateY(-2px);
  }
`;

const ModuleHeader = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
`;

const ModuleName = styled.div`
  font-weight: bold;
  color: #ffffff;
  font-size: 14px;
`;

const ModuleStatus = styled.div`
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: bold;
  background: ${props => props.status === '运行中' ? 'rgba(0, 255, 136, 0.2)' : 'rgba(255, 255, 255, 0.1)'};
  color: ${props => props.status === '运行中' ? '#00ff88' : '#cccccc'};
  border: 1px solid ${props => props.status === '运行中' ? '#00ff88' : 'rgba(255, 255, 255, 0.2)'};
`;

const ModuleDescription = styled.div`
  color: #cccccc;
  font-size: 12px;
  margin-bottom: 8px;
`;

const ModuleEndpoints = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
`;

const EndpointTag = styled.span`
  background: rgba(0, 255, 255, 0.1);
  border: 1px solid rgba(0, 255, 255, 0.3);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 10px;
  color: #00ffff;
  font-family: 'Courier New', monospace;
`;

const ArchitectureSection = styled.div`
  margin-bottom: 20px;
  
  h3 {
    color: #00ffff;
    margin-bottom: 15px;
    font-size: 18px;
  }
`;

const ArchitectureGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
`;

const ArchitectureItem = styled(motion.div)`
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(0, 255, 255, 0.2);
  border-radius: 6px;
  padding: 10px;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(0, 255, 255, 0.4);
  }
`;

const ArchitectureLabel = styled.div`
  color: #00ffff;
  font-size: 11px;
  font-weight: bold;
  margin-bottom: 4px;
  text-transform: uppercase;
`;

const ArchitectureValue = styled.div`
  color: #ffffff;
  font-size: 12px;
  line-height: 1.4;
`;

const TokenSection = styled.div`
  margin-bottom: 32px;
 `;

 // 添加新的样式组件用于水平布局
const HorizontalPerformanceCard = styled(motion.div)`  background: rgba(0, 170, 255, 0.05);
  border: 1px solid rgba(0, 170, 255, 0.2);
  border-radius: 6px;
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;

  &:hover {
    background: rgba(0, 170, 255, 0.1);
    border-color: rgba(0, 170, 255, 0.4);
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(0, 170, 255, 0.2);
  }

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
    animation: cardShimmer 3s infinite;
  }

  @keyframes cardShimmer {
    0% { left: -100%; }
    100% { left: 100%; }
  }`;

const HorizontalPerformanceValue = styled.div`  font-size: 14px;
  font-weight: 600;
  color: #00aaff;
  font-family: 'Source Code Pro', monospace;
  text-shadow: 0 0 6px rgba(0, 170, 255, 0.3);`;

const HorizontalPerformanceLabel = styled.div`  font-size: 12px;
  color: #cccccc;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.3px;`;


const LeftPanel = ({ project, isTransitioning }) => {
  const [isFlipped, setIsFlipped] = useState(false);

  // 当项目切换时重置翻转状态
  useEffect(() => {
    setIsFlipped(false);
  }, [project.basicInfo.title]);

  return (
    <Panel
      initial={{ opacity: 0, x: -50 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5 }}
    >
      <PanelContent>
        {/* 项目标题 */}
        <ProjectTitle
          key={project.basicInfo.title}
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          {project.basicInfo.title}
        </ProjectTitle>
        
                    {/* 项目启动时间 */}
                    <ProjectStartTime>
                      <StartTimeLabel>项目周期</StartTimeLabel>
                      <StartTimeValue>{project.basicInfo.projectTime}</StartTimeValue>
                    </ProjectStartTime>


        {/* 应用维度评估 */}
        <ApplicationInfoSection>
          <ProgressLabel>应用维度评估</ProgressLabel>
          <CoolMetricsList>
            {project.evaluation.map((metric, index) => (
              <CoolMetricItem key={`${project.basicInfo.title}-evaluation-${index}`}>
                <MetricLabel>{metric.label}</MetricLabel>
                <CoolProgressBar>
                  <CoolProgressFill 
                    width={`${metric.percentage}%`} 
                    color={metric.color} 
                    index={index}
                  />
                </CoolProgressBar>
                <CoolMetricValue>{metric.value}</CoolMetricValue>
              </CoolMetricItem>
            ))}
          </CoolMetricsList>
        </ApplicationInfoSection>

        {/* Token消耗统计 */}
        <TokenSection>
          <ProgressLabel>Token消耗</ProgressLabel>
          <TokenGrid>
            <HorizontalPerformanceCard
              key={`${project.basicInfo.title}-token-todayCount`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.1 }}
              whileHover={{ scale: 1.05 }}
            >
              <HorizontalPerformanceLabel>今日总消耗</HorizontalPerformanceLabel>
              <HorizontalPerformanceValue>{project.tokenParse.todayCount}</HorizontalPerformanceValue>
            </HorizontalPerformanceCard>
            <HorizontalPerformanceCard
              key={`${project.basicInfo.title}-token-inCount`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.2 }}
              whileHover={{ scale: 1.05 }}
            >
              <HorizontalPerformanceLabel>输入Token</HorizontalPerformanceLabel>
              <HorizontalPerformanceValue>{project.tokenParse.inCount}</HorizontalPerformanceValue>
            </HorizontalPerformanceCard>
            <HorizontalPerformanceCard
              key={`${project.basicInfo.title}-token-outCount`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.2 }}
              whileHover={{ scale: 1.05 }}
            >
              <HorizontalPerformanceLabel>输出Token</HorizontalPerformanceLabel>
              <HorizontalPerformanceValue>{project.tokenParse.outCount}</HorizontalPerformanceValue>
            </HorizontalPerformanceCard>
            <HorizontalPerformanceCard
              key={`${project.basicInfo.title}-token-avgTime`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.2 }}
              whileHover={{ scale: 1.05 }}
            >
              <HorizontalPerformanceLabel>平均处理时长</HorizontalPerformanceLabel>
              <HorizontalPerformanceValue>{project.tokenParse.avgTime}</HorizontalPerformanceValue>
            </HorizontalPerformanceCard>
          </TokenGrid>
        </TokenSection>


        {/* 核心技能卡片 */}
        <SkillsSection>
          <ProgressLabel>核心技能</ProgressLabel>
          <SkillCardContainer>
            <FlipCard
              key={`${project.basicInfo.title}-skills`}
              isFlipped={isFlipped}
              onClick={() => setIsFlipped(!isFlipped)}
            >
              <CardFront>
                <CardTitle>{project.skills[0].frontTitle}</CardTitle>
                <CardDescription>
                  {project.skills[0].frontDescription}
                </CardDescription>
              </CardFront>
              <CardBack>
                <CardBackTitle>{project.skills[0].backTitle}</CardBackTitle>
                <CardBackDescription>
                  {project.skills[0].backDescription}
                </CardBackDescription>
              </CardBack>
            </FlipCard>
            <SkillIndicators>
              <Indicator active={!isFlipped} />
              <Indicator active={isFlipped} />
            </SkillIndicators>
          </SkillCardContainer>
        </SkillsSection>

      </PanelContent>
    </Panel>
  );
};

export default LeftPanel;
