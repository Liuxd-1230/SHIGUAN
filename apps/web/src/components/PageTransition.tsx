import type { ReactNode } from "react";
import { motion } from "framer-motion";

/**
 * 页面进入过渡（开卷意象：轻微自下方浮现）。
 * 减弱动效由外层 <MotionConfig reducedMotion="user"> 统一处理——Framer 会自动
 * 跳过 transform/opacity 的过渡，状态立即就位。
 */
export default function PageTransition({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}
