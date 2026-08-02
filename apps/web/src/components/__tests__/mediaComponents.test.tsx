import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import PortraitFrame from "../PortraitFrame";
import AssetImage from "../AssetImage";

afterEach(cleanup);

describe("PortraitFrame（保留真实文化，不臆造）", () => {
  it("无图像时退化为姓氏首字，并以 role=img 暴露名称", () => {
    render(<PortraitFrame name="阿努尔夫" />);
    const fig = screen.getByRole("img");
    expect(fig).toHaveAttribute("aria-label", "阿努尔夫 的肖像");
    expect(screen.getByText("阿")).toBeInTheDocument();
  });

  it("展示调用方提供的真实文化标签（不改写）", () => {
    render(<PortraitFrame name="李清照" cultureLabel="宋" />);
    expect(screen.getByText("宋")).toBeInTheDocument();
  });

  it("提供图像时渲染装饰性 img（aria-hidden + 空 alt）", () => {
    const { container } = render(
      <PortraitFrame name="X" imageUrl="/assets/oriental/red-seal.png" />,
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute("alt")).toBe("");
    expect(img).toHaveAttribute("aria-hidden");
  });

  it("图像加载失败时整节点消失（优雅降级）", () => {
    const { container } = render(
      <PortraitFrame name="X" imageUrl="/missing.png" />,
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).toBeTruthy();
    fireEvent.error(img);
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("AssetImage（装饰素材优雅降级）", () => {
  it("默认装饰：空 alt + aria-hidden", () => {
    const { container } = render(<AssetImage src="/assets/oriental/x.png" />);
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute("alt")).toBe("");
    expect(img).toHaveAttribute("aria-hidden");
  });

  it("onError 时整节点消失，不阻塞渲染", () => {
    const { container } = render(<AssetImage src="/missing.png" />);
    const img = container.querySelector("img") as HTMLImageElement;
    fireEvent.error(img);
    expect(container.querySelector("img")).toBeNull();
  });

  it("提供 alt 时暴露于读屏", () => {
    const { container } = render(<AssetImage src="/x.png" alt="山水背景" />);
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).not.toHaveAttribute("aria-hidden");
    expect(img.getAttribute("alt")).toBe("山水背景");
  });
});
