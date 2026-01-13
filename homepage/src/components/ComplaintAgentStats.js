import React, { useState, useEffect } from 'react';
import styled, { keyframes } from 'styled-components';

// 动画定义
const fadeIn = keyframes`
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
`;

const pulse = keyframes`
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
`;

const slideIn = keyframes`
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(0);
  }
`;

const glow = keyframes`
  0%, 100% {
    box-shadow: 0 0 5px rgba(0, 150, 255, 0.5), 0 0 10px rgba(0, 150, 255, 0.3);
  }
  50% {
    box-shadow: 0 0 20px rgba(0, 150, 255, 0.8), 0 0 30px rgba(0, 150, 255, 0.5);
  }
`;

const Container = styled.div`
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #0f1419 100%);
  padding: 40px 20px;
  position: relative;
  overflow-x: hidden;

  &::before {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-image: 
      linear-gradient(rgba(0, 150, 255, 0.05) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0, 150, 255, 0.05) 1px, transparent 1px);
    background-size: 50px 50px;
    z-index: 0;
    pointer-events: none;
  }
`;

const ContentWrapper = styled.div`
  max-width: 1600px;
  margin: 0 auto;
  position: relative;
  z-index: 1;
`;

const Header = styled.div`
  text-align: center;
  margin-bottom: 50px;
  animation: ${fadeIn} 0.8s ease-out;
`;

const Title = styled.h1`
  font-size: 48px;
  font-weight: 700;
  background: linear-gradient(135deg, #00d4ff 0%, #0096ff 50%, #00ff96 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 10px;
  text-shadow: 0 0 40px rgba(0, 150, 255, 0.3);
  letter-spacing: 2px;
`;

const Subtitle = styled.p`
  font-size: 18px;
  color: #8899aa;
  font-weight: 300;
`;

const MetricsGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 25px;
  margin-bottom: 40px;
`;

const MetricCard = styled.div`
  background: rgba(26, 26, 46, 0.6);
  border: 1px solid rgba(0, 150, 255, 0.3);
  border-radius: 16px;
  padding: 30px;
  backdrop-filter: blur(10px);
  animation: ${fadeIn} 0.8s ease-out;
  animation-delay: ${props => props.delay || '0s'};
  animation-fill-mode: both;
  position: relative;
  overflow: hidden;
  transition: all 0.3s ease;

  &:hover {
    transform: translateY(-5px);
    border-color: rgba(0, 150, 255, 0.6);
    box-shadow: 0 10px 30px rgba(0, 150, 255, 0.2);
  }

  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 2px;
    background: linear-gradient(90deg, transparent, #00d4ff, transparent);
    animation: ${slideIn} 2s ease-in-out infinite;
  }
`;

const MetricLabel = styled.div`
  font-size: 14px;
  color: #8899aa;
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 1px;
`;

const MetricValue = styled.div`
  font-size: 36px;
  font-weight: 700;
  color: ${props => props.color || '#00d4ff'};
  margin-bottom: 8px;
  display: flex;
  align-items: baseline;
  gap: 8px;
`;

const MetricUnit = styled.span`
  font-size: 18px;
  font-weight: 400;
  color: #8899aa;
`;

const MetricTrend = styled.div`
  font-size: 14px;
  color: ${props => props.positive ? '#00ff96' : '#ff4444'};
  display: flex;
  align-items: center;
  gap: 5px;

  &::before {
    content: '${props => props.positive ? '▲' : '▼'}';
  }
`;

const ChartsSection = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
  gap: 30px;
  margin-bottom: 40px;

  @media (max-width: 768px) {
    grid-template-columns: 1fr;
  }
`;

const ChartCard = styled.div`
  background: rgba(26, 26, 46, 0.6);
  border: 1px solid rgba(0, 150, 255, 0.3);
  border-radius: 16px;
  padding: 30px;
  backdrop-filter: blur(10px);
  animation: ${fadeIn} 1s ease-out;
  animation-delay: ${props => props.delay || '0s'};
  animation-fill-mode: both;
`;

const ChartTitle = styled.h3`
  font-size: 20px;
  color: #e8e8e8;
  margin-bottom: 25px;
  padding-bottom: 15px;
  border-bottom: 1px solid rgba(0, 150, 255, 0.2);
`;

const LineChart = styled.svg`
  width: 100%;
  height: 300px;
`;

const BarChart = styled.div`
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 300px;
  padding: 20px 0;
  gap: 10px;
`;

const Bar = styled.div`
  flex: 1;
  background: linear-gradient(180deg, #00d4ff 0%, #0096ff 100%);
  border-radius: 8px 8px 0 0;
  position: relative;
  animation: ${slideIn} 1s ease-out;
  animation-delay: ${props => props.delay || '0s'};
  animation-fill-mode: both;
  height: ${props => props.height || '0%'};
  min-width: 40px;
  transition: all 0.3s ease;

  &:hover {
    background: linear-gradient(180deg, #00ff96 0%, #00d4ff 100%);
    animation: ${glow} 1.5s ease-in-out infinite;
  }

  &::after {
    content: '${props => props.label || ''}';
    position: absolute;
    bottom: -25px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 12px;
    color: #8899aa;
    white-space: nowrap;
  }
`;

const BarValue = styled.div`
  position: absolute;
  top: -25px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 14px;
  color: #00d4ff;
  font-weight: 600;
  white-space: nowrap;
`;

const StatusGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
  gap: 25px;
  margin-bottom: 40px;
`;

const StatusCard = styled.div`
  background: rgba(26, 26, 46, 0.6);
  border: 1px solid rgba(0, 150, 255, 0.3);
  border-radius: 16px;
  padding: 25px;
  backdrop-filter: blur(10px);
  animation: ${fadeIn} 1s ease-out;
  animation-delay: ${props => props.delay || '0s'};
  animation-fill-mode: both;
`;

const StatusTitle = styled.h4`
  font-size: 16px;
  color: #e8e8e8;
  margin-bottom: 15px;
  display: flex;
  align-items: center;
  gap: 10px;

  &::before {
    content: '';
    width: 8px;
    height: 8px;
    background: ${props => props.status === 'active' ? '#00ff96' : '#ff9900'};
    border-radius: 50%;
    animation: ${pulse} 2s ease-in-out infinite;
  }
`;

const StatusList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

const StatusItem = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(0, 150, 255, 0.1);
  }
`;

const StatusLabel = styled.span`
  color: #8899aa;
  font-size: 14px;
`;

const StatusValue = styled.span`
  color: #00d4ff;
  font-weight: 600;
  font-size: 14px;
`;

const ProgressBar = styled.div`
  width: 100%;
  height: 8px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 4px;
  overflow: hidden;
  margin-top: 10px;
`;

const ProgressFill = styled.div`
  height: 100%;
  background: linear-gradient(90deg, #00d4ff 0%, #00ff96 100%);
  border-radius: 4px;
  width: ${props => props.width || '0%'};
  transition: width 1s ease-out;
  animation: ${glow} 2s ease-in-out infinite;
`;

const ComplaintAgentStats = () => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // 模拟数据
  const metrics = {
    totalCalls: { value: 125847, unit: '次', trend: 12.5, positive: true },
    successRate: { value: 99.2, unit: '%', trend: 0.8, positive: true },
    avgTokens: { value: 1245, unit: 'tokens', trend: -5.2, positive: true },
    avgResponseTime: { value: 1.23, unit: 's', trend: -8.5, positive: true },
    activeSessions: { value: 342, unit: '个', trend: 15.3, positive: true },
    errorRate: { value: 0.8, unit: '%', trend: -0.3, positive: true },
  };

  // 7天调用量数据
  const callsData = [
    { day: '周一', calls: 15200 },
    { day: '周二', calls: 18500 },
    { day: '周三', calls: 21000 },
    { day: '周四', calls: 19800 },
    { day: '周五', calls: 23500 },
    { day: '周六', calls: 14200 },
    { day: '周日', calls: 13647 },
  ];

  // 24小时调用趋势数据（简化版本，用于折线图）
  const hourlyData = Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    calls: Math.floor(Math.random() * 500) + 300,
  }));

  const maxCalls = Math.max(...callsData.map(d => d.calls));

  // 生成SVG折线图路径
  const generateLinePath = (data) => {
    const width = 100;
    const height = 100;
    const padding = 5;
    
    const maxValue = Math.max(...data.map(d => d.calls));
    const points = data.map((d, i) => {
      const x = (i / (data.length - 1)) * (width - 2 * padding) + padding;
      const y = height - ((d.calls / maxValue) * (height - 2 * padding) + padding);
      return `${x},${y}`;
    });
    
    return `M ${points.join(' L ')}`;
  };

  return (
    <Container>
      <ContentWrapper>
        <Header>
          <Title>投诉智能体调用量统计</Title>
          <Subtitle>实时监控系统运行状态与性能指标 | Real-time Monitoring Dashboard</Subtitle>
        </Header>

        {/* 核心指标卡片 */}
        <MetricsGrid>
          <MetricCard delay="0.1s">
            <MetricLabel>总调用次数</MetricLabel>
            <MetricValue color="#00d4ff">
              {metrics.totalCalls.value.toLocaleString()}
              <MetricUnit>{metrics.totalCalls.unit}</MetricUnit>
            </MetricValue>
            <MetricTrend positive={metrics.totalCalls.positive}>
              {Math.abs(metrics.totalCalls.trend)}% 较上周
            </MetricTrend>
          </MetricCard>

          <MetricCard delay="0.2s">
            <MetricLabel>请求成功率</MetricLabel>
            <MetricValue color="#00ff96">
              {metrics.successRate.value}
              <MetricUnit>{metrics.successRate.unit}</MetricUnit>
            </MetricValue>
            <MetricTrend positive={metrics.successRate.positive}>
              {Math.abs(metrics.successRate.trend)}% 较上周
            </MetricTrend>
          </MetricCard>

          <MetricCard delay="0.3s">
            <MetricLabel>平均Token数</MetricLabel>
            <MetricValue color="#ff9900">
              {metrics.avgTokens.value.toLocaleString()}
              <MetricUnit>{metrics.avgTokens.unit}</MetricUnit>
            </MetricValue>
            <MetricTrend positive={metrics.avgTokens.positive}>
              {Math.abs(metrics.avgTokens.trend)}% 较上周
            </MetricTrend>
          </MetricCard>

          <MetricCard delay="0.4s">
            <MetricLabel>平均响应时间</MetricLabel>
            <MetricValue color="#a855f7">
              {metrics.avgResponseTime.value}
              <MetricUnit>{metrics.avgResponseTime.unit}</MetricUnit>
            </MetricValue>
            <MetricTrend positive={metrics.avgResponseTime.positive}>
              {Math.abs(metrics.avgResponseTime.trend)}% 较上周
            </MetricTrend>
          </MetricCard>

          <MetricCard delay="0.5s">
            <MetricLabel>活跃会话数</MetricLabel>
            <MetricValue color="#00d4ff">
              {metrics.activeSessions.value}
              <MetricUnit>{metrics.activeSessions.unit}</MetricUnit>
            </MetricValue>
            <MetricTrend positive={metrics.activeSessions.positive}>
              {Math.abs(metrics.activeSessions.trend)}% 较上周
            </MetricTrend>
          </MetricCard>

          <MetricCard delay="0.6s">
            <MetricLabel>错误率</MetricLabel>
            <MetricValue color="#ff4444">
              {metrics.errorRate.value}
              <MetricUnit>{metrics.errorRate.unit}</MetricUnit>
            </MetricValue>
            <MetricTrend positive={metrics.errorRate.positive}>
              {Math.abs(metrics.errorRate.trend)}% 较上周
            </MetricTrend>
          </MetricCard>
        </MetricsGrid>

        {/* 图表区域 */}
        <ChartsSection>
          {/* 7天调用量柱状图 */}
          <ChartCard delay="0.7s">
            <ChartTitle>近7天调用量趋势</ChartTitle>
            <BarChart>
              {callsData.map((data, index) => (
                <Bar
                  key={data.day}
                  height={`${(data.calls / maxCalls) * 100}%`}
                  label={data.day}
                  delay={`${0.8 + index * 0.1}s`}
                >
                  <BarValue>{(data.calls / 1000).toFixed(1)}k</BarValue>
                </Bar>
              ))}
            </BarChart>
          </ChartCard>

          {/* 24小时调用趋势折线图 */}
          <ChartCard delay="0.8s">
            <ChartTitle>24小时调用趋势</ChartTitle>
            <LineChart viewBox="0 0 100 100" preserveAspectRatio="none">
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
              
              {/* 背景网格 */}
              {[0, 25, 50, 75, 100].map(y => (
                <line
                  key={`grid-${y}`}
                  x1="5"
                  y1={y}
                  x2="95"
                  y2={y}
                  stroke="rgba(136, 153, 170, 0.1)"
                  strokeWidth="0.2"
                />
              ))}
              
              {/* 区域填充 */}
              <path
                d={`${generateLinePath(hourlyData)} L 95,100 L 5,100 Z`}
                fill="url(#areaGradient)"
              />
              
              {/* 折线 */}
              <path
                d={generateLinePath(hourlyData)}
                fill="none"
                stroke="url(#lineGradient)"
                strokeWidth="0.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              
              {/* 数据点 */}
              {hourlyData.map((d, i) => {
                const maxValue = Math.max(...hourlyData.map(d => d.calls));
                const x = (i / (hourlyData.length - 1)) * 90 + 5;
                const y = 100 - ((d.calls / maxValue) * 90 + 5);
                return (
                  <circle
                    key={`point-${i}`}
                    cx={x}
                    cy={y}
                    r="0.8"
                    fill="#00d4ff"
                    opacity={i % 3 === 0 ? 1 : 0.3}
                  >
                    {i % 3 === 0 && (
                      <animate
                        attributeName="r"
                        values="0.8;1.5;0.8"
                        dur="2s"
                        repeatCount="indefinite"
                      />
                    )}
                  </circle>
                );
              })}
            </LineChart>
          </ChartCard>
        </ChartsSection>

        {/* 系统状态 */}
        <StatusGrid>
          <StatusCard delay="0.9s">
            <StatusTitle status="active">实时性能指标</StatusTitle>
            <StatusList>
              <StatusItem>
                <StatusLabel>CPU 使用率</StatusLabel>
                <StatusValue>45.2%</StatusValue>
              </StatusItem>
              <ProgressBar>
                <ProgressFill width={mounted ? "45.2%" : "0%"} />
              </ProgressBar>
              
              <StatusItem>
                <StatusLabel>内存使用率</StatusLabel>
                <StatusValue>62.8%</StatusValue>
              </StatusItem>
              <ProgressBar>
                <ProgressFill width={mounted ? "62.8%" : "0%"} />
              </ProgressBar>
              
              <StatusItem>
                <StatusLabel>网络带宽</StatusLabel>
                <StatusValue>235 Mbps</StatusValue>
              </StatusItem>
              <ProgressBar>
                <ProgressFill width={mounted ? "78%" : "0%"} />
              </ProgressBar>
            </StatusList>
          </StatusCard>

          <StatusCard delay="1s">
            <StatusTitle status="active">请求统计</StatusTitle>
            <StatusList>
              <StatusItem>
                <StatusLabel>今日请求数</StatusLabel>
                <StatusValue>23,547</StatusValue>
              </StatusItem>
              <StatusItem>
                <StatusLabel>成功请求</StatusLabel>
                <StatusValue>23,359</StatusValue>
              </StatusItem>
              <StatusItem>
                <StatusLabel>失败请求</StatusLabel>
                <StatusValue>188</StatusValue>
              </StatusItem>
              <StatusItem>
                <StatusLabel>平均QPS</StatusLabel>
                <StatusValue>156 req/s</StatusValue>
              </StatusItem>
            </StatusList>
          </StatusCard>

          <StatusCard delay="1.1s">
            <StatusTitle status="active">Token 消耗统计</StatusTitle>
            <StatusList>
              <StatusItem>
                <StatusLabel>今日总消耗</StatusLabel>
                <StatusValue>2.85M tokens</StatusValue>
              </StatusItem>
              <StatusItem>
                <StatusLabel>输入Token</StatusLabel>
                <StatusValue>1.42M tokens</StatusValue>
              </StatusItem>
              <StatusItem>
                <StatusLabel>输出Token</StatusLabel>
                <StatusValue>1.43M tokens</StatusValue>
              </StatusItem>
              <StatusItem>
                <StatusLabel>预估成本</StatusLabel>
                <StatusValue>¥285.00</StatusValue>
              </StatusItem>
            </StatusList>
          </StatusCard>
        </StatusGrid>
      </ContentWrapper>
    </Container>
  );
};

export default ComplaintAgentStats;

