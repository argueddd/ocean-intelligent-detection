import React, { useState, useEffect } from 'react';
import styled from 'styled-components';
import { motion } from 'framer-motion';
// import { projectConfig } from '../data/projectConfig';

const Panel = styled(motion.div)`
  flex: 0 0 clamp(300px, 28vw, 400px);
  background: 
    linear-gradient(145deg, rgba(0, 0, 0, 0.85), rgba(10, 20, 40, 0.75));
  border: 1px solid rgba(0, 255, 150, 0.2);
  border-radius: 12px;
  padding: clamp(16px, 2vw, 32px);
  backdrop-filter: blur(10px);
  box-shadow: 
    0 4px 20px rgba(0, 0, 0, 0.4),
    0 0 20px rgba(0, 255, 150, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  position: relative;
  min-height: 0;

  @media (max-width: 1400px) {
    flex: 0 0 clamp(280px, 30vw, 350px);
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

const SectionTitle = styled.h3`
  color: #00ffff;
  margin-bottom: 20px;
  font-size: 16px;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  text-shadow: 0 0 6px rgba(0, 255, 255, 0.3);
`;

// API 统计组件
const ApiStatsSection = styled.div`
  margin-bottom: 32px;
`;

const StatsGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
`;

const StatCard = styled.div`
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(0, 255, 150, 0.2);
  border-radius: 8px;
  padding: 12px;
  text-align: center;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(0, 255, 150, 0.08);
    border-color: rgba(0, 255, 150, 0.3);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 255, 150, 0.1);
  }
`;

const StatValue = styled.div`
  font-size: 16px;
  font-weight: 600;
  color: #ffffff;
  margin-bottom: 4px;
  font-family: 'Source Code Pro', monospace;
`;

const StatLabel = styled.div`
  font-size: 10px;
  color: #cccccc;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

// 使用场景组件
const UseCasesSection = styled.div`
  margin-bottom: 32px;
`;

const UseCaseItem = styled.div`
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(255, 255, 255, 0.05);
    border-color: rgba(255, 255, 255, 0.2);
    transform: translateY(-1px);
  }
`;

const UseCaseTitle = styled.div`
  font-size: 13px;
  font-weight: 600;
  color: #00ffaa;
  margin-bottom: 6px;
  font-family: 'Inter', sans-serif;
`;

const UseCaseDescription = styled.div`
  font-size: 12px;
  color: #cccccc;
  line-height: 1.5;
  font-family: 'Inter', sans-serif;
`;

// 实时监控组件

const TagsGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 25px;
`;

const Tag = styled(motion.span)`
  padding: 6px 10px;
  background: rgba(0, 255, 150, 0.08);
  border: 1px solid rgba(0, 255, 150, 0.2);
  border-radius: 12px;
  text-align: center;
  font-size: 11px;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  cursor: default;
  transition: all 0.3s ease;
  color: #00ffaa;

  &:hover {
    background: rgba(0, 255, 150, 0.12);
    border-color: rgba(0, 255, 150, 0.3);
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(0, 255, 150, 0.1);
  }
`;

const TechStackSection = styled.div`
  margin-bottom: 32px;
`;

const TechStackGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
`;

const TechItem = styled.div`
  background: rgba(0, 255, 150, 0.05);
  border: 1px solid rgba(0, 255, 150, 0.2);
  border-radius: 8px;
  padding: 12px;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(0, 255, 150, 0.08);
    border-color: rgba(0, 255, 150, 0.3);
    transform: translateY(-1px);
  }
`;

const TechLabel = styled.div`
  font-size: 10px;
  color: #cccccc;
  margin-bottom: 4px;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

const TechValue = styled.div`
  font-size: 12px;
  color: #00ffaa;
  font-weight: 600;
  font-family: 'Source Code Pro', monospace;
`;

// 个人标签
const PersonalTagsSection = styled.div`
  margin-bottom: 32px;
`;

const TagsContainer = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
`;

const PersonalTag = styled(motion.span)`
  padding: 4px 8px;
  background: rgba(0, 170, 255, 0.1);
  border: 1px solid rgba(0, 170, 255, 0.3);
  border-radius: 12px;
  font-size: 10px;
  color: #00aaff;
  font-family: 'Inter', sans-serif;
  font-weight: 500;
  transition: all 0.3s ease;
  cursor: pointer;

  &:hover {
    background: rgba(0, 170, 255, 0.2);
    border-color: rgba(0, 170, 255, 0.5);
    transform: translateY(-1px);
  }
`;


// 智能体性能指标 - 紧凑卡片式
const PerformanceCardsGrid = styled.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
`;

// 功能模块样式组件
const ModulesSection = styled.div`
  margin-bottom: 16px;
  
  h3 {
    color: #00ffff;
    margin-bottom: 10px;
    font-size: 16px;
  }
`;

const ModulesList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 6px;
`;

const ModuleItem = styled(motion.div)`
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(0, 255, 255, 0.15);
  border-radius: 6px;
  padding: 8px;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(255, 255, 255, 0.05);
    border-color: rgba(0, 255, 255, 0.25);
    transform: translateY(-1px);
  }
`;

const FirstModuleItem = styled(motion.div)`
  background: rgba(0, 170, 255, 0.08);
  border: 1px solid rgba(0, 170, 255, 0.3);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 12px;
  transition: all 0.3s ease;
  min-height: 100px;

  &:hover {
    background: rgba(0, 170, 255, 0.12);
    border-color: rgba(0, 170, 255, 0.5);
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 170, 255, 0.2);
  }
`;

const ModuleHeader = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
`;

const ModuleName = styled.div`
  font-weight: bold;
  color: #ffffff;
  font-size: 12px;
`;

const ModuleStatus = styled.div`
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 9px;
  font-weight: bold;
  background: ${props => props.status === '运行中' ? 'rgba(0, 255, 136, 0.2)' : 'rgba(255, 255, 255, 0.1)'};
  color: ${props => props.status === '运行中' ? '#00ff88' : '#cccccc'};
  border: 1px solid ${props => props.status === '运行中' ? '#00ff88' : 'rgba(255, 255, 255, 0.2)'};
`;

const ModuleDescription = styled.div`
  color: #cccccc;
  font-size: 10px;
  margin-bottom: 4px;
`;

const EndpointsList = styled.ul`
  list-style: none;
  padding-left: 0;
  margin-top: 3px;
`;

const EndpointItem = styled.li`
  color: #00ffaa;
  font-size: 9px;
  margin-bottom: 2px;
  font-family: 'Source Code Pro', monospace;

  &::before {
    content: '› ';
    color: #00aaff;
    margin-right: 3px;
  }
`;

// 系统架构图样式组件
const ArchitectureDiagramSection = styled.div`
  margin-bottom: 20px;
`;

const ArchitectureDiagram = styled.div`
  background: rgba(0, 170, 255, 0.05);
  border: 1px solid rgba(0, 170, 255, 0.2);
  border-radius: 8px;
  padding: 16px;
  position: relative;
  overflow: hidden;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(0, 170, 255, 0.08);
    border-color: rgba(0, 170, 255, 0.3);
  }
`;

const ArchitectureImage = styled.img`
  width: 100%;
  height: auto;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.3s ease;
  transform: ${props => props.isZoomed ? `scale(${props.isZoomed ? 'clamp(1.2, 3vw, 1.8)' : '1'}) translateY(-50%)` : 'scale(1)'};
  z-index: ${props => props.isZoomed ? '1000' : '1'};
  position: ${props => props.isZoomed ? 'fixed' : 'static'};
  top: ${props => props.isZoomed ? '50%' : 'auto'};
  left: ${props => props.isZoomed ? '50%' : 'auto'};
  margin-left: ${props => props.isZoomed ? '-50%' : '0'};
  max-width: ${props => props.isZoomed ? '90vw' : '100%'};
  max-height: ${props => props.isZoomed ? '80vh' : 'auto'};
  box-shadow: ${props => props.isZoomed ? '0 0 50px rgba(0, 0, 0, 0.8)' : 'none'};

  &:hover {
    opacity: 0.8;
  }

  @media (max-width: 768px) {
    max-width: ${props => props.isZoomed ? '95vw' : '100%'};
    max-height: ${props => props.isZoomed ? '70vh' : 'auto'};
  }
`;

const ZoomButton = styled.button`
  width: 100%;
  margin-top: 12px;
  padding: 8px 16px;
  background: linear-gradient(45deg, #00aaff, #00ffaa);
  border: 1px solid rgba(0, 170, 255, 0.3);
  border-radius: 6px;
  color: #fff;
  font-size: 12px;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 2px 8px rgba(0, 170, 255, 0.2);
  position: ${props => props.isZoomed ? 'fixed' : 'static'};
  top: ${props => props.isZoomed ? '80%' : 'auto'};
  left: ${props => props.isZoomed ? '50%' : 'auto'};
  transform: ${props => props.isZoomed ? 'translateX(-50%)' : 'none'};
  z-index: ${props => props.isZoomed ? '1001' : '1'};
  width: ${props => props.isZoomed ? 'auto' : '100%'};
  min-width: ${props => props.isZoomed ? '120px' : 'auto'};

  &:hover {
    background: linear-gradient(45deg, #00bbff, #00ffbb);
    box-shadow: 0 4px 12px rgba(0, 170, 255, 0.3);
    transform: ${props => props.isZoomed ? 'translateX(-50%) translateY(-1px)' : 'translateY(-1px)'};
  }

  &:active {
    transform: translateY(0);
  }
`;

const ArchitectureFlow = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
`;

const FlowNode = styled(motion.div)`
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px;
  background: ${props => {
    if (props.type === 'input') return 'rgba(0, 255, 150, 0.1)';
    if (props.type === 'process') return 'rgba(0, 170, 255, 0.1)';
    if (props.type === 'output') return 'rgba(255, 107, 107, 0.1)';
    return 'rgba(255, 255, 255, 0.05)';
  }};
  border: 1px solid ${props => {
    if (props.type === 'input') return 'rgba(0, 255, 150, 0.3)';
    if (props.type === 'process') return 'rgba(0, 170, 255, 0.3)';
    if (props.type === 'output') return 'rgba(255, 107, 107, 0.3)';
    return 'rgba(255, 255, 255, 0.1)';
  }};
  border-radius: 8px;
  min-width: 60px;
  transition: all 0.3s ease;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 170, 255, 0.2);
  }
`;

const NodeIcon = styled.div`
  font-size: 20px;
  margin-bottom: 6px;
  animation: pulse 2s infinite;
  
  @keyframes pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.1); }
  }
`;

const NodeLabel = styled.div`
  font-size: 10px;
  color: #ffffff;
  font-weight: 600;
  text-align: center;
  font-family: 'Inter', sans-serif;
`;

const FlowArrow = styled.div`
  font-size: 16px;
  color: #00aaff;
  font-weight: bold;
  animation: arrowPulse 2s infinite;
  
  @keyframes arrowPulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
`;

const ArchitectureDetails = styled.div`
  display: flex;
  justify-content: space-around;
  gap: 8px;
`;

const DetailItem = styled(motion.div)`
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  flex: 1;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(255, 255, 255, 0.05);
    transform: translateY(-1px);
  }
`;
const ProgressLabel = styled.div`
  font-size: 16px;
  margin-bottom: 20px;
  color: #00ffff;
  font-weight: 500;
  font-family: 'Inter', sans-serif;
  text-shadow: 0 0 6px rgba(0, 255, 255, 0.3);
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

const MetricLabel = styled.div`
  font-size: 11px;
  color: #cccccc;
  margin-bottom: 4px;
  font-family: 'Inter', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

// 添加折线图相关样式
const ChartCard = styled.div`  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(0, 255, 255, 0.15);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 24px;`;

const ChartTitle = styled.h3`  color: #00ffff;
  margin-bottom: 16px;
  font-size: 16px;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
  text-shadow: 0 0 6px rgba(0, 255, 255, 0.3);`;

const LineChartContainer = styled.div`  width: 100%;
  height: 200px;`;

const LineChartSvg = styled.svg`  width: 100%;
  height: 100%;`;

const DetailIcon = styled.div`
  font-size: 14px;
  margin-bottom: 4px;
`;

const DetailText = styled.div`
  font-size: 8px;
  color: #cccccc;
  text-align: center;
  font-family: 'Inter', sans-serif;
`;
const ProgressSection = styled.div`
  margin-bottom: 32px;
`;

// 应用信息部分
const ApplicationInfoSection = styled.div`
  margin-bottom: 32px;
`;

// 酷炫柱状图
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


const RightPanel = ({ project, isTransitioning }) => {
  const [isZoomed, setIsZoomed] = useState(false);

  // 当项目切换时重置缩放状态
  useEffect(() => {
    setIsZoomed(false);
  }, [project.basicInfo.title]);

   // 生成折线图数据点
  const generateLineChartData = () => {
    // 这里应该使用真实的项目数据，这里只是示例数据
    const data = project.callTrendData || [
      { hour: 0, calls: 120 },
      { hour: 2, calls: 80 },
      { hour: 4, calls: 60 },
      { hour: 6, calls: 200 },
      { hour: 8, calls: 420 },
      { hour: 10, calls: 580 },
      { hour: 12, calls: 620 },
      { hour: 14, calls: 550 },
      { hour: 16, calls: 480 },
      { hour: 18, calls: 650 },
      { hour: 20, calls: 720 },
      { hour: 22, calls: 400 },
      { hour: 24, calls: 200 }
    ];

    return data;
  };

  // 将数据转换为 SVG 路径
  const createLinePath = (data) => {
    if (!data || data.length === 0) return '';

    const maxX = 95; // SVG 图表的 X 轴最大值
    const minX = 10; // SVG 图表的 X 轴最小值
    const maxY = 5;  // SVG 图表的 Y 轴最大值 (顶部)
    const minY = 90; // SVG 图表的 Y 轴最小值 (底部)

    // 找到数据中的最大调用次数，用于缩放
    const maxCalls = Math.max(...data.map(d => d.calls));

    const points = data.map((point, index) => {
      // 将小时映射到 X 坐标 (0-24小时 映射到 10-95)
      const x = minX + (point.hour / 24) * (maxX - minX);

      // 将调用次数映射到 Y 坐标 (0-maxCalls 映射到 90-5)
      const y = minY - (point.calls / maxCalls) * (minY - maxY);

      return `${x},${y}`;
    });

    return `M ${points.join(' L ')}`;
  };

  // 创建区域填充路径
  const createAreaPath = (data) => {
    if (!data || data.length === 0) return '';

    const maxX = 95;
    const minX = 10;
    const minY = 90;

    // 找到数据中的最大调用次数
    const maxCalls = Math.max(...data.map(d => d.calls));

    const points = data.map((point, index) => {
      const x = minX + (point.hour / 24) * (maxX - minX);
      const y = minY - (point.calls / maxCalls) * (minY - 5);
      return `${x},${y}`;
    });

    return `M ${points.join(' L ')} L 95,90 L 10,90 Z`;
  };

  // 创建数据点
  const createDataPoints = (data) => {
    if (!data || data.length === 0) return null;

    const maxX = 95;
    const minX = 10;
    const minY = 90;

    // 找到数据中的最大调用次数
    const maxCalls = Math.max(...data.map(d => d.calls));

    return data.map((point, index) => {
      const x = minX + (point.hour / 24) * (maxX - minX);
      const y = minY - (point.calls / maxCalls) * (minY - 5);

      return (
        <circle
          key={index}
          cx={x}
          cy={y}
          r="1"
          fill="#00d4ff"
          stroke="rgba(0, 212, 255, 0.5)"
          strokeWidth="0.5"
        />
      );
    });
  };

  const chartData = generateLineChartData();
  const linePath = createLinePath(chartData);
  const areaPath = createAreaPath(chartData);
  const dataPoints = createDataPoints(chartData);

  return (
    <Panel
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5 }}
    >
      <PanelContent>

         {/* 智能体性能指标 */}
        <ProgressSection>
          <ProgressLabel>智能体性能指标</ProgressLabel>
          <PerformanceCardsGrid>
            <PerformanceCard
              key={`${project.basicInfo.title}-accuracy`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.1 }}
              whileHover={{ scale: 1.05 }}
            >
              <PerformanceValue>{project.performance.accuracy}</PerformanceValue>
              <PerformanceLabel>准确率</PerformanceLabel>
            </PerformanceCard>
            <PerformanceCard
              key={`${project.basicInfo.title}-responseTime`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.2 }}
              whileHover={{ scale: 1.05 }}
            >
              <PerformanceValue>{project.performance.responseTime}</PerformanceValue>
              <PerformanceLabel>响应时间</PerformanceLabel>
            </PerformanceCard>
            <PerformanceCard
              key={`${project.basicInfo.title}-processingSpeed`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.3 }}
              whileHover={{ scale: 1.05 }}
            >
              <PerformanceValue>{project.performance.processingSpeed}</PerformanceValue>
              <PerformanceLabel>处理速度</PerformanceLabel>
            </PerformanceCard>
            <PerformanceCard
              key={`${project.basicInfo.title}-stability`}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.4 }}
              whileHover={{ scale: 1.05 }}
            >
              <PerformanceValue>{project.performance.stability}</PerformanceValue>
              <PerformanceLabel>稳定性</PerformanceLabel>
            </PerformanceCard>
          </PerformanceCardsGrid>
        </ProgressSection>


        {/* 横进度柱状图 */}
        <ApplicationInfoSection>
          <ProgressLabel>横进度柱状图</ProgressLabel>
          <CoolMetricsList>
            {project.barValue.map((metric, index) => (
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


       
         {/* 24小时调用趋势折线图 */}
        <ChartCard>
          <ChartTitle>24小时调用趋势</ChartTitle>
          <LineChartContainer>
            <LineChartSvg viewBox="0 0 100 100" preserveAspectRatio="none">
              <defs>
                <linearGradient id="lineGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#00d4ff" />
                  <stop offset="50%" stopColor="#0096ff" />
                  <stop offset="100%" stopColor="#00ff96" />
                </linearGradient>
                <linearGradient id="areaGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="rgba(0, 212, 255, 0.3)" />
                  <stop offset="100%" stopColor="rgba(0, 212, 255, 0.0)" />
                </linearGradient>
              </defs>

              {/* Y轴标签 */}
              <text x="4" y="8" fontSize="2.5" fill="#8899aa" textAnchor="end">800</text>
              <text x="4" y="28" fontSize="2.5" fill="#8899aa" textAnchor="end">600</text>
              <text x="4" y="48" fontSize="2.5" fill="#8899aa" textAnchor="end">400</text>
              <text x="4" y="68" fontSize="2.5" fill="#8899aa" textAnchor="end">200</text>
              <text x="4" y="88" fontSize="2.5" fill="#8899aa" textAnchor="end">0</text>

              {/* X轴标签 */}
              <text x="10" y="95" fontSize="2.5" fill="#8899aa" textAnchor="middle">0</text>
              <text x="30" y="95" fontSize="2.5" fill="#8899aa" textAnchor="middle">6</text>
              <text x="50" y="95" fontSize="2.5" fill="#8899aa" textAnchor="middle">12</text>
              <text x="70" y="95" fontSize="2.5" fill="#8899aa" textAnchor="middle">18</text>
              <text x="90" y="95" fontSize="2.5" fill="#8899aa" textAnchor="middle">24</text>

              {/* 背景网格 */}
              <line x1="8" y1="0" x2="95" y2="0" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>
              <line x1="8" y1="25" x2="95" y2="25" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>
              <line x1="8" y1="50" x2="95" y2="50" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>
              <line x1="8" y1="75" x2="95" y2="75" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>
              <line x1="8" y1="100" x2="95" y2="100" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>

              {/* 垂直网格线 */}
              <line x1="10" y1="5" x2="10" y2="95" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>
              <line x1="30" y1="5" x2="30" y2="95" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>
              <line x1="50" y1="5" x2="50" y2="95" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>
              <line x1="70" y1="5" x2="70" y2="95" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>
              <line x1="90" y1="5" x2="90" y2="95" stroke="rgba(136, 153, 170, 0.1)" strokeWidth="0.2"/>

              {/* 区域填充 */}
              <path d={areaPath} fill="url(#areaGradient)" />

              {/* 折线 */}
              <path d={linePath} fill="none" stroke="url(#lineGradient)" strokeWidth="0.5" strokeLinecap="round" strokeLinejoin="round" />

              {/* 数据点 */}
              {dataPoints}
            </LineChartSvg>
          </LineChartContainer>
        </ChartCard>

      </PanelContent>
    </Panel>
  );
};

export default RightPanel;
