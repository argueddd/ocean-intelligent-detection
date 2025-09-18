import React from 'react';
import styled from 'styled-components';
import { motion } from 'framer-motion';

const NavigationContainer = styled.div`
  height: clamp(60px, 8vh, 80px);
  background: 
    linear-gradient(180deg, 
      rgba(0, 0, 0, 0.9) 0%, 
      rgba(20, 20, 40, 0.8) 50%, 
      rgba(0, 0, 0, 0.9) 100%);
  border-top: 1px solid rgba(0, 170, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(10px);
  position: relative;

  @media (max-width: 768px) {
    height: clamp(50px, 6vh, 60px);
  }
`;

const NavContainer = styled.div`
  display: flex;
  gap: clamp(8px, 1vw, 15px);
  flex-wrap: wrap;
  justify-content: center;
  max-width: 90vw;

  @media (max-width: 768px) {
    gap: clamp(5px, 0.8vw, 8px);
  }

  @media (max-width: 480px) {
    gap: 4px;
  }
`;

const NavButton = styled(motion.button)`
  width: clamp(40px, 4vw, 55px);
  height: clamp(40px, 4vw, 55px);
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(0, 170, 255, 0.3);
  border-radius: 10px;
  color: #ffffff;
  font-size: clamp(12px, 1.2vw, 16px);
  font-weight: 600;
  font-family: 'JetBrains Mono', 'Monaco', 'Consolas', monospace;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(10px);
  min-width: 40px;
  min-height: 40px;

  @media (max-width: 768px) {
    min-width: 35px;
    min-height: 35px;
  }

  @media (max-width: 480px) {
    min-width: 32px;
    min-height: 32px;
  }

  &.active {
    background: linear-gradient(45deg, #00aaff, #00ffaa);
    border-color: #00aaff;
    color: #000;
    box-shadow: 
      0 4px 15px rgba(0, 170, 255, 0.4),
      inset 0 1px 0 rgba(255, 255, 255, 0.3);
  }

  &:hover:not(.active) {
    background: rgba(0, 170, 255, 0.15);
    border-color: rgba(0, 170, 255, 0.5);
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 170, 255, 0.3);
  }
`;

const BottomNavigation = ({ currentIndex, totalProjects, onProjectChange }) => {
  return (
    <NavigationContainer>
      <NavContainer>
        {Array.from({ length: totalProjects }, (_, index) => (
          <NavButton
            key={index}
            className={index === currentIndex ? 'active' : ''}
            onClick={() => onProjectChange(index)}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            animate={{
              scale: index === currentIndex ? 1.1 : 1,
            }}
            transition={{ duration: 0.2 }}
          >
            {String(index + 1).padStart(2, '0')}
          </NavButton>
        ))}
      </NavContainer>
    </NavigationContainer>
  );
};

export default BottomNavigation;
