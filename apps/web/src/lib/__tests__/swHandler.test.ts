import { describe, it, expect, vi } from "vitest";
import { decideFetch, respondTo, type FetchContext } from "../swHandler";

const ORIGIN = "https://shiguan.example";

function ctx(p: Partial<FetchContext> & { url: string }): FetchContext {
  const url = new URL(p.url);
  return {
    url,
    method: p.method ?? "GET",
    mode: p.mode ?? "navigate",
    hasAuthorization: p.hasAuthorization ?? false,
    origin: url.origin,
    swOrigin: p.swOrigin ?? ORIGIN,
  };
}

function fakeCaches(initial: Record<string, Response> = {}) {
  const store = new Map<string, Response>(Object.entries(initial));
  const keyOf = (u: string | Request) =>
    typeof u === "string" ? u : new URL(u.url).pathname;
  return {
    _store: store,
    async open() {
      return {
        async match(u: string | Request) {
          return store.get(keyOf(u)) ?? null;
        },
        async put(u: string | Request, r: Response) {
          store.set(keyOf(u), r);
        },
      };
    },
  } as unknown as CacheStorage;
}

/** 用 Proxy 强制响应 type（真实 Response.type 只读，无法直接赋值）。 */
function withType(r: Response, type: string): Response {
  return new Proxy(r, {
    get(target, prop) {
      if (prop === "type") return type;
      return Reflect.get(target, prop);
    },
  });
}

function basicResponse(body = "<html></html>"): Response {
  return withType(
    new Response(body, {
      status: 200,
      headers: { "content-type": "text/html" },
    }),
    "basic",
  );
}

describe("swHandler.decideFetch（分支顺序）", () => {
  it("导航 /characters 归为 navigate-app（可离线回退）", () => {
    expect(decideFetch(ctx({ url: `${ORIGIN}/characters` })).kind).toBe("navigate-app");
  });

  it("导航 /characters/arnulf_001 归为 navigate-app（深链接）", () => {
    expect(
      decideFetch(ctx({ url: `${ORIGIN}/characters/arnulf_001` })).kind,
    ).toBe("navigate-app");
  });

  it("/api/characters 即使是导航也不回退缓存（私有路径，直接 pass）", () => {
    const d = decideFetch(ctx({ url: `${ORIGIN}/api/characters` }));
    expect(d.kind).toBe("pass");
  });

  it("Authorization 请求不缓存（pass）", () => {
    const d = decideFetch(
      ctx({ url: `${ORIGIN}/characters`, hasAuthorization: true }),
    );
    expect(d.kind).toBe("pass");
  });

  it("POST 不缓存（pass）", () => {
    const d = decideFetch(ctx({ url: `${ORIGIN}/characters`, method: "POST" }));
    expect(d.kind).toBe("pass");
  });

  it("未知公开路径导航不被错误缓存（network-only）", () => {
    const d = decideFetch(ctx({ url: `${ORIGIN}/some/random/page` }));
    expect(d.kind).toBe("network-only");
  });

  it("同源静态资源归为 static-cache", () => {
    const d = decideFetch(
      ctx({ url: `${ORIGIN}/assets/app.abc.js`, mode: "cors" }),
    );
    expect(d.kind).toBe("static-cache");
  });
});

describe("swHandler.respondTo（离线回退与缓存）", () => {
  it("离线 /characters 回退到缓存的 /index.html", async () => {
    const caches = fakeCaches({
      "/index.html": basicResponse("<!doctype html><html><body>app</body></html>"),
    });
    const fetchImpl = vi.fn().mockRejectedValue(new Error("offline"));
    const decision = decideFetch(ctx({ url: `${ORIGIN}/characters` }));
    const res = await respondTo(
      decision,
      new Request(`${ORIGIN}/characters`),
      { fetchImpl, caches, cacheName: "v1", indexFallback: "/index.html" },
    );
    expect(res).toBe(caches._store.get("/index.html"));
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("离线 /characters/arnulf_001 回退到缓存的 /index.html", async () => {
    const caches = fakeCaches({
      "/index.html": basicResponse("app"),
    });
    const fetchImpl = vi.fn().mockRejectedValue(new Error("offline"));
    const decision = decideFetch(ctx({ url: `${ORIGIN}/characters/arnulf_001` }));
    const res = await respondTo(
      decision,
      new Request(`${ORIGIN}/characters/arnulf_001`),
      { fetchImpl, caches, cacheName: "v1", indexFallback: "/index.html" },
    );
    expect(res).toBe(caches._store.get("/index.html"));
  });

  it("/api/characters 导航失败时不回退缓存（直接抛出网络错误）", async () => {
    const caches = fakeCaches({ "/index.html": basicResponse("app") });
    const fetchImpl = vi.fn().mockRejectedValue(new Error("network"));
    const decision = decideFetch(ctx({ url: `${ORIGIN}/api/characters` }));
    await expect(
      respondTo(decision, new Request(`${ORIGIN}/api/characters`), {
        fetchImpl,
        caches,
        cacheName: "v1",
        indexFallback: "/index.html",
      }),
    ).rejects.toThrow("network");
  });

  it("static-cache：命中缓存直接返回，不访问网络", async () => {
    const cached = basicResponse("cached-asset");
    const caches = fakeCaches({ "/assets/app.js": cached });
    const fetchImpl = vi.fn();
    const decision = decideFetch(ctx({ url: `${ORIGIN}/assets/app.js`, mode: "cors" }));
    const res = await respondTo(
      decision,
      new Request(`${ORIGIN}/assets/app.js`),
      { fetchImpl, caches, cacheName: "v1", indexFallback: "/index.html" },
    );
    expect(res).toBe(cached);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("static-cache：未命中则回源并把 basic 响应写入缓存", async () => {
    const caches = fakeCaches();
    const fetched = basicResponse("fresh-asset");
    const fetchImpl = vi.fn().mockResolvedValue(fetched);
    const decision = decideFetch(ctx({ url: `${ORIGIN}/assets/app.js`, mode: "cors" }));
    const res = await respondTo(
      decision,
      new Request(`${ORIGIN}/assets/app.js`),
      { fetchImpl, caches, cacheName: "v1", indexFallback: "/index.html" },
    );
    expect(res).toBe(fetched);
    // 写入缓存后再次请求应命中（不再访问网络）
    const again = await respondTo(
      decision,
      new Request(`${ORIGIN}/assets/app.js`),
      { fetchImpl, caches, cacheName: "v1", indexFallback: "/index.html" },
    );
    expect(again).toBeInstanceOf(Response);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("static-cache：非 basic（如 opaque/跨源）响应不被写入缓存", async () => {
    const caches = fakeCaches();
    const fetched = withType(new Response("x", { status: 200 }), "opaque");
    const fetchImpl = vi.fn().mockResolvedValue(fetched);
    const decision = decideFetch(ctx({ url: `${ORIGIN}/assets/app.js`, mode: "cors" }));
    const res = await respondTo(
      decision,
      new Request(`${ORIGIN}/assets/app.js`),
      { fetchImpl, caches, cacheName: "v1", indexFallback: "/index.html" },
    );
    expect(res).toBe(fetched);
    expect(caches._store.size).toBe(0); // 未写入
  });
});
