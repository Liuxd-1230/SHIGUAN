import { motion } from "framer-motion";
import { navigate, ROUTES } from "../lib/router";
import MuseumSurface from "../components/MuseumSurface";
import SealButton from "../components/SealButton";
import InkDivider from "../components/InkDivider";
import AssetImage from "../components/AssetImage";
import LocalSavesPanel from "../components/LocalSavesPanel";
import { SealMark } from "../components/icons";

export default function StartPage() {
  return (
    <div className="mx-auto max-w-3xl px-5 py-10">
      {/* 山水舆图意象（装饰，缺失素材时退化为纸白，不阻塞） */}
      <section className="hero-mountain relative overflow-hidden rounded-2xl border border-ink-400/40 bg-paper-100/60 px-6 py-10 text-center">
        <div
          className="pointer-events-none absolute inset-0 bg-gradient-to-b from-paper-50/70 to-paper-100/90"
          aria-hidden
        />
        <div className="relative">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          >
            <SealMark
              size={40}
              className="mx-auto mb-3 animate-seal-stamp text-cinnabar-700"
            />
            <h1 className="font-serif text-3xl font-bold text-ink-950 sm:text-4xl">
              读取存档，重写一生
            </h1>
            <p className="mx-auto mt-3 max-w-xl text-ink-700">
              史官 SHIGUAN 是一款面向《十字军之王 III》玩家的 AI 历史传记生成器。
              导入存档、选定人物，程序基于存档中的可靠证据，为人物立传。
            </p>
          </motion.div>
        </div>
      </section>

      <div className="mt-6">
        <MuseumSurface variant="raised" className="p-6">
          <h2 className="font-serif text-lg font-bold text-ink-900">开始演示</h2>
          <p className="mt-2 text-sm text-ink-600">
            当前为 Mock 演示环境：载入的是
            <strong className="text-ink-900">“明确标注为非真实解析”</strong>
            的示例数据，用于走通“解析 → 选人 → 看传记 → 看证据”的完整流程。
            尚未接入真实 CK3 存档解析。
          </p>
          <div className="mt-5 flex items-center gap-3">
            {/* 朱砂印章：品牌/主操作的局部装饰（优雅降级，缺失则整节点消失） */}
            <AssetImage
              src="/assets/oriental/red-seal.webp"
              className="h-12 w-12 shrink-0 animate-seal-stamp opacity-90"
              eager
            />
            <SealButton
              variant="primary"
              seal
              onClick={() => navigate(ROUTES.parse)}
            >
              载入示例存档
            </SealButton>
          </div>
        </MuseumSurface>
      </div>

      <div className="mt-5">
        <MuseumSurface variant="raised" className="p-5">
          <h3 className="text-sm font-medium text-ink-800">隐私说明</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-500">
            <li>真实存档默认只在本地处理，不离开你的机器。</li>
            <li>远程模型需你显式开启，且仅发送压缩后的结构化档案。</li>
            <li>本项目不会提交任何真实存档或密钥。</li>
          </ul>
        </MuseumSurface>
      </div>

      <InkDivider variant="seal" className="my-6" />

      {/* 本地存档浏览器（后端可用时显示；后端未启动则自动隐藏，继续 Mock 演示） */}
      <LocalSavesPanel />

      <p className="mt-6 text-center text-xs text-ink-500">
        <button
          type="button"
          onClick={() => navigate(ROUTES.designlab)}
          className="underline-offset-2 hover:text-cinnabar-700 hover:underline"
        >
          查看视觉设计实验室（临时）
        </button>
      </p>
    </div>
  );
}
