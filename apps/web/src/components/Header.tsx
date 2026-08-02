import { useRoute, navigate } from "../lib/router";

const BREADCRUMB: Record<string, string> = {
  start: "起始",
  parse: "解析存档",
  select: "选择人物",
  bio: "人物传记",
  designlab: "设计实验室",
  notfound: "未找到",
};

export default function Header() {
  const route = useRoute();
  const key = route.name === "bio" ? "bio" : route.name;
  return (
    <header className="border-b border-ink-400/40 bg-paper-100/80 backdrop-blur safe-top">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3">
        <button
          type="button"
          onClick={() => navigate("/")}
          className="flex items-baseline gap-3 text-left"
          aria-label="返回起始页"
        >
          <span className="font-serif text-xl font-bold tracking-wide text-ink-950">
            史官 <span className="text-cinnabar-700">SHIGUAN</span>
          </span>
          <span className="hidden text-xs text-ink-500 sm:inline">
            读取存档，重写一生
          </span>
        </button>
        <nav className="text-xs text-ink-500" aria-label="页面位置">
          当前：<span className="text-ink-800">{BREADCRUMB[key]}</span>
        </nav>
      </div>
    </header>
  );
}
