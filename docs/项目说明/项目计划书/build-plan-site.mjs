import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.join(currentDir, "AgentLuo项目计划书.md");
const indexPath = path.join(currentDir, "index.html");
const namedHtmlPath = path.join(currentDir, "AgentLuo项目计划书.html");

const source = fs.readFileSync(sourcePath, "utf8").replace(/\r\n/g, "\n");
const title =
  source.match(/<h1[^>]*>\s*([^<]+?)\s*<\/h1>/i)?.[1]?.trim() ??
  "AgentLuo项目计划书";
const subtitle =
  source.match(/<p[^>]*>\s*<i>\s*([^<]+?)\s*<\/i>\s*<\/p>/i)?.[1]?.trim() ??
  "最终她会于光影中降临，走上台前和你相遇";

const bodySource = source
  .replace(/<h1[^>]*>[\s\S]*?<\/h1>\s*/i, "")
  .replace(/<p[^>]*>\s*<i>[\s\S]*?<\/i>\s*<\/p>\s*/i, "");

const chapters = [];
let activeChapter = null;

for (const line of bodySource.split("\n")) {
  const chapterMatch = line.match(/^##\s+(.+?)\s*$/);
  if (chapterMatch) {
    activeChapter = {
      title: chapterMatch[1].trim(),
      lines: [],
    };
    chapters.push(activeChapter);
    continue;
  }

  if (activeChapter) {
    activeChapter.lines.push(line);
  }
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function normalizeHref(href) {
  if (/^https?:\/\//i.test(href) || href.startsWith("#")) {
    return href;
  }

  const clean = href.replace(/^\.\//, "");
  const githubDocs = {
    "TODO.md":
      "https://github.com/SheepLiu712/Agent-LuoTianyi/blob/main/docs/TODO.md",
    "开发指引.md":
      "https://github.com/SheepLiu712/Agent-LuoTianyi/blob/main/docs/%E5%BC%80%E5%8F%91%E6%8C%87%E5%BC%95.md",
  };

  return githubDocs[clean] ?? href;
}

function renderInline(value) {
  let html = escapeHtml(value);

  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_, label, href) => {
      const normalized = normalizeHref(
        href
          .replaceAll("&amp;", "&")
          .replaceAll("&quot;", '"')
          .replaceAll("&lt;", "<")
          .replaceAll("&gt;", ">"),
      );
      const external = /^https?:\/\//i.test(normalized);
      const attributes = external
        ? ' target="_blank" rel="noreferrer noopener"'
        : "";
      return `<a href="${escapeHtml(normalized)}"${attributes}>${label}</a>`;
    },
  );

  html = html
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/&lt;(\/?)(b|i|em|strong)&gt;/gi, "<$1$2>");

  return html;
}

function renderBlocks(lines, chapterIndex) {
  const blocks = [];
  const toc = [];
  let paragraph = [];
  let subheadingIndex = 0;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${renderInline(paragraph.join(" ").trim())}</p>`);
    paragraph = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      flushParagraph();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{3,4})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      subheadingIndex += 1;
      const level = headingMatch[1].length;
      const heading = headingMatch[2].trim();
      const headingId = `section-${chapterIndex}-${subheadingIndex}`;
      blocks.push(
        `<h${level} id="${headingId}">${renderInline(heading)}</h${level}>`,
      );
      toc.push({ level, title: heading, id: headingId });
      continue;
    }

    if (trimmed === "---") {
      flushParagraph();
      blocks.push('<div class="soft-divider" aria-hidden="true"><span></span></div>');
      continue;
    }

    if (trimmed.startsWith("> ")) {
      flushParagraph();
      const quoteLines = [];
      while (index < lines.length && lines[index].trim().startsWith("> ")) {
        quoteLines.push(lines[index].trim().slice(2));
        index += 1;
      }
      index -= 1;
      blocks.push(
        `<blockquote>${renderInline(quoteLines.join(" "))}</blockquote>`,
      );
      continue;
    }

    if (/^-\s+/.test(trimmed)) {
      flushParagraph();
      const items = [];
      while (index < lines.length && /^-\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^-\s+/, ""));
        index += 1;
      }
      index -= 1;
      blocks.push(
        `<ul>${items
          .map((item) => `<li>${renderInline(item)}</li>`)
          .join("")}</ul>`,
      );
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      flushParagraph();
      const items = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      index -= 1;
      blocks.push(
        `<ol>${items
          .map((item) => `<li>${renderInline(item)}</li>`)
          .join("")}</ol>`,
      );
      continue;
    }

    paragraph.push(trimmed);
  }

  flushParagraph();

  return { html: blocks.join("\n"), toc };
}

function chapterMeta(chapter, index) {
  const numbered = chapter.title.match(/^(\d{2})\s+(.+)$/);
  if (numbered) {
    return {
      id: `chapter-${numbered[1]}`,
      number: numbered[1],
      shortTitle: numbered[2],
      fullTitle: chapter.title,
      menuTitle: numbered[2],
    };
  }

  return {
    id: `chapter-${String(index + 1).padStart(2, "0")}`,
    number: "终",
    shortTitle: chapter.title,
    fullTitle: chapter.title,
    menuTitle: chapter.title,
  };
}

const renderedChapters = chapters.map((chapter, index) => {
  const meta = chapterMeta(chapter, index);
  return {
    ...meta,
    ...renderBlocks(chapter.lines, index + 1),
  };
});

const allPages = [
  { id: "cover", title: "序章" },
  ...renderedChapters.map((chapter) => ({
    id: chapter.id,
    title: chapter.menuTitle,
  })),
];

function renderNavItems(className = "") {
  return allPages
    .map(
      (page, index) => `
        <button
          class="chapter-link ${className}"
          type="button"
          data-page-target="${page.id}"
          data-page-index="${index}"
        >
          <span class="chapter-link-index">${String(index).padStart(2, "0")}</span>
          <span>${escapeHtml(page.title)}</span>
        </button>`,
    )
    .join("");
}

function renderChapterToc(chapter) {
  const entries = chapter.toc.filter((item) => item.level === 3);
  if (entries.length < 2) return "";

  return `
    <nav class="chapter-toc" aria-label="${escapeHtml(chapter.menuTitle)}节内目录">
      <span class="chapter-toc-label">本章内容</span>
      <div class="chapter-toc-links">
        ${entries
          .map(
            (item) =>
              `<a href="#${item.id}" data-subsection-link>${renderInline(
                item.title,
              )}</a>`,
          )
          .join("")}
      </div>
    </nav>`;
}

function renderChapterPage(chapter, index) {
  return `
    <section
      class="page chapter-page"
      id="${chapter.id}"
      data-page-index="${index + 1}"
      aria-labelledby="${chapter.id}-title"
      hidden
    >
      <article class="reading-sheet">
        <header class="chapter-header">
          <span class="chapter-number">${escapeHtml(chapter.number)}</span>
          <h2 id="${chapter.id}-title">${escapeHtml(chapter.shortTitle)}</h2>
          <span class="chapter-flourish" aria-hidden="true"></span>
        </header>
        ${renderChapterToc(chapter)}
        <div class="chapter-body">
          ${chapter.html}
        </div>
      </article>
    </section>`;
}

const pagesJson = JSON.stringify(allPages).replaceAll("<", "\\u003c");
const generatedAt = new Date().toISOString();

const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#eef8ff">
  <meta name="description" content="AgentLuo项目的愿景、目标、实现路径、阶段规划与协作治理。">
  <title>${escapeHtml(title)}</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #30435b;
      --ink-soft: #60738b;
      --blue: #6baed8;
      --blue-deep: #4f8fbd;
      --pink: #e9a6bc;
      --pink-soft: #f8d8e4;
      --paper: rgba(255, 255, 255, 0.78);
      --paper-strong: rgba(255, 255, 255, 0.9);
      --line: rgba(103, 147, 180, 0.2);
      --shadow: 0 30px 80px rgba(72, 111, 145, 0.16);
      --nav-height: 68px;
      --content-width: 780px;
      --shell-width: 1180px;
      font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun", serif;
      font-synthesis: none;
      text-rendering: optimizeLegibility;
    }

    * {
      box-sizing: border-box;
    }

    html {
      scroll-behavior: smooth;
      scroll-padding-top: calc(var(--nav-height) + 28px);
      background: #eef8ff;
    }

    body {
      min-width: 320px;
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 8%, rgba(168, 221, 245, 0.72), transparent 29rem),
        radial-gradient(circle at 89% 16%, rgba(250, 201, 219, 0.65), transparent 25rem),
        radial-gradient(circle at 75% 78%, rgba(194, 225, 247, 0.58), transparent 30rem),
        radial-gradient(circle at 16% 88%, rgba(250, 218, 228, 0.55), transparent 26rem),
        linear-gradient(135deg, #f4fbff 0%, #fff9fc 48%, #eef8ff 100%);
      background-attachment: fixed;
      font-size: 18px;
      line-height: 1.95;
      overflow-x: hidden;
    }

    body::before,
    body::after {
      position: fixed;
      z-index: -1;
      width: 38vw;
      height: 38vw;
      border-radius: 50%;
      filter: blur(75px);
      opacity: 0.26;
      content: "";
      pointer-events: none;
    }

    body::before {
      top: -15vw;
      right: -9vw;
      background: #f1a9c4;
    }

    body::after {
      bottom: -16vw;
      left: -12vw;
      background: #8dc9ec;
    }

    button,
    a {
      -webkit-tap-highlight-color: transparent;
    }

    button {
      font: inherit;
    }

    a {
      color: var(--blue-deep);
      text-decoration-color: rgba(79, 143, 189, 0.34);
      text-decoration-thickness: 0.08em;
      text-underline-offset: 0.2em;
    }

    a:hover {
      color: #d5789a;
      text-decoration-color: currentColor;
    }

    :focus-visible {
      outline: 3px solid rgba(79, 143, 189, 0.42);
      outline-offset: 4px;
    }

    .skip-link {
      position: fixed;
      z-index: 1000;
      top: 10px;
      left: 10px;
      padding: 8px 14px;
      border-radius: 10px;
      background: white;
      transform: translateY(-150%);
    }

    .skip-link:focus {
      transform: translateY(0);
    }

    .reading-progress {
      position: fixed;
      z-index: 101;
      top: 0;
      left: 0;
      width: 100%;
      height: 3px;
      background: rgba(255, 255, 255, 0.38);
    }

    .reading-progress-bar {
      width: 0;
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #73bde6, #efabc2);
      box-shadow: 0 0 16px rgba(118, 181, 220, 0.5);
      transition: width 180ms ease;
    }

    .topbar {
      position: fixed;
      z-index: 100;
      top: 3px;
      right: 0;
      left: 0;
      height: var(--nav-height);
      border-bottom: 1px solid rgba(103, 147, 180, 0.16);
      background: rgba(249, 253, 255, 0.72);
      box-shadow: 0 10px 38px rgba(84, 122, 154, 0.08);
      backdrop-filter: blur(22px) saturate(1.3);
    }

    .topbar-inner {
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      width: min(calc(100% - 32px), var(--shell-width));
      height: 100%;
      margin: 0 auto;
    }

    .brand-button,
    .menu-button {
      display: inline-flex;
      align-items: center;
      border: 0;
      color: var(--ink);
      background: transparent;
      cursor: pointer;
    }

    .brand-button {
      gap: 10px;
      justify-self: start;
      padding: 8px;
      border-radius: 12px;
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }

    .brand-mark {
      display: grid;
      width: 31px;
      height: 31px;
      place-items: center;
      border: 1px solid rgba(255, 255, 255, 0.8);
      border-radius: 50% 50% 48% 52%;
      color: white;
      background: linear-gradient(135deg, #86caed, #edabc3);
      box-shadow: 0 7px 18px rgba(110, 172, 209, 0.24);
      font-family: Georgia, serif;
      font-size: 16px;
    }

    .current-chapter {
      max-width: 38vw;
      overflow: hidden;
      color: var(--ink-soft);
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 13px;
      font-weight: 650;
      letter-spacing: 0.12em;
      text-align: center;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .menu-button {
      gap: 9px;
      justify-self: end;
      padding: 9px 12px;
      border: 1px solid rgba(103, 147, 180, 0.18);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.58);
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 13px;
      font-weight: 650;
    }

    .menu-icon {
      position: relative;
      width: 17px;
      height: 12px;
      border-top: 1.5px solid currentColor;
      border-bottom: 1.5px solid currentColor;
    }

    .menu-icon::after {
      position: absolute;
      top: 4px;
      right: 0;
      left: 0;
      border-top: 1.5px solid currentColor;
      content: "";
    }

    .site-shell {
      display: grid;
      grid-template-columns: 218px minmax(0, 1fr);
      gap: 48px;
      width: min(calc(100% - 48px), var(--shell-width));
      margin: 0 auto;
      padding-top: calc(var(--nav-height) + 42px);
      padding-bottom: 110px;
    }

    .desktop-nav {
      position: sticky;
      top: calc(var(--nav-height) + 32px);
      align-self: start;
      max-height: calc(100vh - var(--nav-height) - 64px);
      padding: 14px;
      overflow-y: auto;
      border: 1px solid rgba(255, 255, 255, 0.72);
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.47);
      box-shadow: 0 22px 55px rgba(70, 111, 146, 0.1);
      backdrop-filter: blur(20px);
      scrollbar-width: thin;
    }

    .nav-eyebrow {
      display: block;
      margin: 4px 10px 13px;
      color: #7790a5;
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 11px;
      font-weight: 750;
      letter-spacing: 0.22em;
      text-transform: uppercase;
    }

    .chapter-link {
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr);
      gap: 9px;
      align-items: center;
      width: 100%;
      margin: 3px 0;
      padding: 9px 10px;
      border: 0;
      border-radius: 13px;
      color: #647b8f;
      background: transparent;
      cursor: pointer;
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 13px;
      line-height: 1.4;
      text-align: left;
      transition: color 160ms ease, background 160ms ease, transform 160ms ease;
    }

    .chapter-link:hover {
      color: var(--blue-deep);
      background: rgba(255, 255, 255, 0.7);
      transform: translateX(2px);
    }

    .chapter-link[aria-current="page"] {
      color: #3f789f;
      background: linear-gradient(120deg, rgba(203, 235, 250, 0.85), rgba(252, 222, 232, 0.68));
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.62);
      font-weight: 720;
    }

    .chapter-link-index {
      color: #96acbe;
      font-size: 10px;
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.08em;
    }

    .content-stage {
      min-width: 0;
    }

    .page {
      width: 100%;
    }

    .page[hidden] {
      display: none !important;
    }

    .page.page-entering > .cover-card,
    .page.page-entering > .reading-sheet {
      animation: chapter-reveal 620ms cubic-bezier(0.16, 1, 0.3, 1) both;
      will-change: opacity, transform;
    }

    @keyframes chapter-reveal {
      from {
        opacity: 0;
        transform: translateY(26px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .cover-page {
      display: grid;
      min-height: calc(100vh - var(--nav-height) - 96px);
      place-items: center;
    }

    .cover-card {
      position: relative;
      width: min(100%, 820px);
      padding: clamp(58px, 10vw, 118px) clamp(26px, 8vw, 88px);
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.8);
      border-radius: 44px;
      background:
        linear-gradient(145deg, rgba(255, 255, 255, 0.78), rgba(255, 255, 255, 0.43)),
        radial-gradient(circle at 80% 18%, rgba(246, 187, 211, 0.34), transparent 28%),
        radial-gradient(circle at 13% 82%, rgba(124, 196, 235, 0.3), transparent 30%);
      box-shadow: var(--shadow);
      text-align: center;
      backdrop-filter: blur(28px) saturate(1.25);
    }

    .cover-card::before,
    .cover-card::after {
      position: absolute;
      border-radius: 50%;
      content: "";
      pointer-events: none;
    }

    .cover-card::before {
      top: 36px;
      right: 46px;
      width: 86px;
      height: 86px;
      border: 1px solid rgba(230, 157, 187, 0.24);
      box-shadow:
        22px 44px 0 -28px rgba(127, 190, 226, 0.32),
        -520px 360px 0 -18px rgba(238, 176, 202, 0.2);
    }

    .cover-card::after {
      bottom: 42px;
      left: 56px;
      width: 8px;
      height: 8px;
      background: rgba(100, 175, 217, 0.52);
      box-shadow:
        22px -14px 0 rgba(235, 165, 193, 0.52),
        44px 8px 0 rgba(127, 190, 226, 0.36),
        590px -390px 0 rgba(235, 165, 193, 0.34);
    }

    .cover-eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      margin-bottom: 26px;
      color: #7097b3;
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 11px;
      font-weight: 750;
      letter-spacing: 0.28em;
      text-transform: uppercase;
    }

    .cover-eyebrow::before,
    .cover-eyebrow::after {
      width: 28px;
      height: 1px;
      background: linear-gradient(90deg, transparent, #99c7e2);
      content: "";
    }

    .cover-eyebrow::after {
      transform: rotate(180deg);
    }

    .cover-card h1 {
      margin: 0;
      color: #324a61;
      font-size: clamp(34px, 6vw, 63px);
      font-weight: 650;
      letter-spacing: 0.08em;
      line-height: 1.22;
      text-wrap: balance;
    }

    .cover-rule {
      display: block;
      width: 66px;
      height: 2px;
      margin: 34px auto 30px;
      border-radius: 999px;
      background: linear-gradient(90deg, #8bc8e8, #efabc4);
    }

    .cover-quote {
      max-width: 560px;
      margin: 0 auto;
      color: #667c91;
      font-size: clamp(17px, 2.5vw, 22px);
      font-style: italic;
      letter-spacing: 0.06em;
      line-height: 1.9;
    }

    .cover-enter {
      display: inline-flex;
      gap: 12px;
      align-items: center;
      margin-top: 46px;
      padding: 12px 21px;
      border: 1px solid rgba(103, 147, 180, 0.17);
      border-radius: 999px;
      color: #517d9b;
      background: rgba(255, 255, 255, 0.68);
      box-shadow: 0 12px 30px rgba(91, 137, 170, 0.1);
      cursor: pointer;
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.08em;
      transition: transform 160ms ease, box-shadow 160ms ease;
    }

    .cover-enter:hover {
      box-shadow: 0 15px 34px rgba(91, 137, 170, 0.16);
      transform: translateY(-2px);
    }

    .reading-sheet {
      width: min(100%, var(--content-width));
      min-height: 68vh;
      margin: 0 auto;
      padding: clamp(42px, 6vw, 72px) clamp(24px, 6vw, 72px) 78px;
      border: 1px solid rgba(255, 255, 255, 0.78);
      border-radius: 36px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.83), rgba(255, 255, 255, 0.68)),
        radial-gradient(circle at 90% 2%, rgba(251, 216, 229, 0.3), transparent 24rem);
      box-shadow: var(--shadow);
      backdrop-filter: blur(24px) saturate(1.15);
    }

    .chapter-header {
      margin-bottom: 48px;
      text-align: center;
    }

    .chapter-number {
      display: inline-grid;
      min-width: 45px;
      height: 45px;
      margin-bottom: 18px;
      padding: 0 10px;
      place-items: center;
      border: 1px solid rgba(255, 255, 255, 0.8);
      border-radius: 50%;
      color: white;
      background: linear-gradient(135deg, #76bce3, #eaa9c0);
      box-shadow: 0 12px 28px rgba(93, 152, 190, 0.22);
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
    }

    .chapter-header h2 {
      margin: 0;
      color: #334b62;
      font-size: clamp(29px, 5vw, 44px);
      font-weight: 650;
      letter-spacing: 0.08em;
      line-height: 1.35;
      text-wrap: balance;
    }

    .chapter-flourish {
      display: block;
      width: 72px;
      height: 1px;
      margin: 27px auto 0;
      background: linear-gradient(90deg, transparent, #83c0e2 25%, #e9a8bf 75%, transparent);
    }

    .chapter-toc {
      margin: -12px 0 44px;
      padding: 18px 20px 20px;
      border: 1px solid rgba(104, 153, 187, 0.16);
      border-radius: 20px;
      background: linear-gradient(120deg, rgba(224, 244, 253, 0.58), rgba(254, 232, 240, 0.48));
      text-align: center;
    }

    .chapter-toc-label {
      display: block;
      margin-bottom: 10px;
      color: #8097aa;
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 10px;
      font-weight: 780;
      letter-spacing: 0.2em;
    }

    .chapter-toc-links {
      display: flex;
      flex-wrap: wrap;
      gap: 7px 15px;
      justify-content: center;
    }

    .chapter-toc a {
      color: #607e94;
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 12px;
      text-decoration: none;
    }

    .chapter-toc a::before {
      margin-right: 6px;
      color: #dd97b1;
      content: "·";
    }

    .chapter-body {
      color: var(--ink);
    }

    .chapter-body p {
      margin: 0 0 1.35em;
      text-align: justify;
      text-justify: inter-ideograph;
    }

    .chapter-page:last-of-type .chapter-body,
    .chapter-page:last-of-type .chapter-body p {
      text-align: center;
    }

    .chapter-body strong,
    .chapter-body b {
      color: #3f6f91;
      font-weight: 720;
    }

    .chapter-body h3,
    .chapter-body h4 {
      position: relative;
      color: #3c5870;
      text-align: center;
      text-wrap: balance;
      scroll-margin-top: calc(var(--nav-height) + 24px);
    }

    .chapter-body h3 {
      margin: 3.2em 0 1.5em;
      padding-top: 0.25em;
      font-size: clamp(22px, 3.3vw, 29px);
      font-weight: 680;
      letter-spacing: 0.06em;
      line-height: 1.55;
    }

    .chapter-body h3::before {
      display: block;
      width: 24px;
      height: 3px;
      margin: 0 auto 16px;
      border-radius: 99px;
      background: linear-gradient(90deg, #7bbfe4, #ecabc1);
      content: "";
    }

    .chapter-body h4 {
      margin: 2.5em 0 1.15em;
      font-size: clamp(18px, 2.8vw, 22px);
      font-weight: 700;
      letter-spacing: 0.05em;
    }

    .chapter-body h4::after {
      display: block;
      width: 42px;
      height: 1px;
      margin: 11px auto 0;
      background: rgba(111, 169, 204, 0.36);
      content: "";
    }

    .chapter-body ul,
    .chapter-body ol {
      margin: 1.2em 0 1.7em;
      padding: 17px 22px 17px 46px;
      border: 1px solid rgba(111, 169, 204, 0.14);
      border-radius: 19px;
      background: rgba(246, 251, 254, 0.7);
    }

    .chapter-body ol {
      background: rgba(255, 248, 251, 0.64);
    }

    .chapter-body li {
      margin: 0.42em 0;
      padding-left: 0.35em;
    }

    .chapter-body li::marker {
      color: #79acd0;
      font-weight: 700;
    }

    .chapter-body blockquote {
      margin: 1.7em 0;
      padding: 17px 21px;
      border: 0;
      border-left: 3px solid #e7a1ba;
      border-radius: 0 16px 16px 0;
      color: #60778b;
      background: linear-gradient(90deg, rgba(250, 224, 234, 0.48), rgba(255, 255, 255, 0.2));
      font-style: normal;
    }

    .chapter-body code {
      padding: 0.12em 0.38em;
      border-radius: 6px;
      color: #5d6c7a;
      background: rgba(119, 171, 203, 0.12);
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 0.88em;
    }

    .soft-divider {
      display: grid;
      margin: 3.5em 0;
      place-items: center;
    }

    .soft-divider span {
      width: 88px;
      height: 1px;
      background: linear-gradient(90deg, transparent, rgba(111, 169, 204, 0.56), rgba(231, 161, 186, 0.56), transparent);
    }

    .quick-pager {
      position: fixed;
      z-index: 90;
      top: 50%;
      right: 22px;
      left: 22px;
      display: flex;
      justify-content: space-between;
      pointer-events: none;
      transform: translateY(-50%);
    }

    .pager-button {
      display: grid;
      width: 48px;
      height: 48px;
      place-items: center;
      border: 1px solid rgba(255, 255, 255, 0.8);
      border-radius: 50%;
      color: #668aa3;
      background: rgba(255, 255, 255, 0.7);
      box-shadow: 0 14px 34px rgba(75, 118, 150, 0.16);
      cursor: pointer;
      font-size: 22px;
      pointer-events: auto;
      backdrop-filter: blur(16px);
      transition: opacity 160ms ease, transform 160ms ease, color 160ms ease;
    }

    .pager-button:hover {
      color: #d77f9f;
      transform: scale(1.06);
    }

    .pager-button:disabled {
      opacity: 0;
      pointer-events: none;
    }

    .drawer-backdrop {
      position: fixed;
      z-index: 200;
      inset: 0;
      border: 0;
      background: rgba(42, 66, 86, 0.22);
      opacity: 0;
      pointer-events: none;
      backdrop-filter: blur(4px);
      transition: opacity 200ms ease;
    }

    .mobile-drawer {
      position: fixed;
      z-index: 201;
      top: 0;
      right: 0;
      width: min(86vw, 360px);
      height: 100dvh;
      padding: 24px 18px;
      overflow-y: auto;
      border-left: 1px solid rgba(255, 255, 255, 0.72);
      background:
        linear-gradient(160deg, rgba(249, 253, 255, 0.96), rgba(255, 247, 251, 0.95)),
        radial-gradient(circle at 90% 10%, rgba(239, 171, 196, 0.22), transparent 45%);
      box-shadow: -28px 0 70px rgba(61, 93, 119, 0.18);
      transform: translateX(105%);
      transition: transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1);
    }

    body.drawer-open {
      overflow: hidden;
    }

    body.drawer-open .drawer-backdrop {
      opacity: 1;
      pointer-events: auto;
    }

    body.drawer-open .mobile-drawer {
      transform: translateX(0);
    }

    .drawer-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 18px;
      padding: 0 8px 14px;
      border-bottom: 1px solid rgba(103, 147, 180, 0.15);
    }

    .drawer-title {
      color: #45637a;
      font-family: ui-sans-serif, system-ui, sans-serif;
      font-size: 14px;
      font-weight: 750;
      letter-spacing: 0.1em;
    }

    .drawer-close {
      display: grid;
      width: 36px;
      height: 36px;
      place-items: center;
      border: 0;
      border-radius: 50%;
      color: #61798b;
      background: rgba(119, 171, 203, 0.1);
      cursor: pointer;
      font-size: 22px;
    }

    .drawer-nav .chapter-link {
      padding: 12px;
      font-size: 14px;
    }

    .page-announcer {
      position: fixed;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
    }

    @media (max-width: 1180px) {
      .quick-pager {
        right: 10px;
        left: 10px;
      }

      .pager-button {
        width: 42px;
        height: 42px;
      }
    }

    @media (max-width: 900px) {
      :root {
        --nav-height: 60px;
      }

      body {
        padding-bottom: 72px;
        font-size: 17px;
        line-height: 1.9;
      }

      .topbar-inner {
        width: min(calc(100% - 20px), var(--shell-width));
      }

      .brand-button {
        padding-left: 2px;
      }

      .brand-button > span:last-child {
        display: none;
      }

      .current-chapter {
        max-width: 50vw;
        font-size: 12px;
      }

      .menu-button {
        padding: 8px 10px;
      }

      .menu-button > span:last-child {
        display: none;
      }

      .site-shell {
        display: block;
        width: min(calc(100% - 28px), 820px);
        padding-top: calc(var(--nav-height) + 25px);
        padding-bottom: 36px;
      }

      .desktop-nav {
        display: none;
      }

      .cover-page {
        min-height: calc(100dvh - var(--nav-height) - 50px);
      }

      .cover-card {
        border-radius: 32px;
      }

      .reading-sheet {
        padding-right: clamp(20px, 6vw, 50px);
        padding-left: clamp(20px, 6vw, 50px);
        border-radius: 28px;
      }

      .chapter-header {
        margin-bottom: 40px;
      }

      .chapter-body p {
        text-align: left;
      }

      .quick-pager {
        top: auto;
        right: 0;
        bottom: 0;
        left: 0;
        height: 62px;
        padding: 8px max(14px, env(safe-area-inset-right)) calc(8px + env(safe-area-inset-bottom)) max(14px, env(safe-area-inset-left));
        border-top: 1px solid rgba(103, 147, 180, 0.16);
        background: rgba(249, 253, 255, 0.84);
        box-shadow: 0 -10px 34px rgba(75, 118, 150, 0.1);
        backdrop-filter: blur(18px);
        transform: none;
      }

      .pager-button {
        width: 44px;
        height: 44px;
        border-color: rgba(103, 147, 180, 0.15);
        box-shadow: none;
        background: rgba(255, 255, 255, 0.68);
      }
    }

    @media (max-width: 520px) {
      body {
        font-size: 16.5px;
        line-height: 1.88;
      }

      .site-shell {
        width: min(calc(100% - 18px), 820px);
      }

      .cover-card {
        padding: 62px 20px;
        border-radius: 27px;
      }

      .cover-card h1 {
        font-size: clamp(31px, 11vw, 45px);
        letter-spacing: 0.04em;
      }

      .cover-quote {
        font-size: 17px;
      }

      .reading-sheet {
        padding: 36px 18px 58px;
        border-radius: 24px;
      }

      .chapter-number {
        min-width: 40px;
        height: 40px;
      }

      .chapter-header h2 {
        font-size: 30px;
        letter-spacing: 0.05em;
      }

      .chapter-toc {
        margin-right: -2px;
        margin-left: -2px;
        padding: 15px 13px 17px;
      }

      .chapter-toc-links {
        gap: 7px 12px;
      }

      .chapter-body h3 {
        margin-top: 2.8em;
        font-size: 23px;
      }

      .chapter-body h4 {
        font-size: 19px;
      }

      .chapter-body ul,
      .chapter-body ol {
        margin-right: -3px;
        margin-left: -3px;
        padding: 14px 15px 14px 36px;
        border-radius: 16px;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      html {
        scroll-behavior: auto;
      }

      *,
      *::before,
      *::after {
        scroll-behavior: auto !important;
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
      }
    }

    @media print {
      body {
        background: white;
        font-size: 12pt;
      }

      .topbar,
      .desktop-nav,
      .quick-pager,
      .mobile-drawer,
      .drawer-backdrop,
      .reading-progress {
        display: none !important;
      }

      .site-shell {
        display: block;
        width: 100%;
        padding: 0;
      }

      .page[hidden] {
        display: block !important;
      }

      .cover-page {
        min-height: 95vh;
        break-after: page;
      }

      .cover-card,
      .reading-sheet {
        width: 100%;
        border: 0;
        box-shadow: none;
        background: white;
      }

      .chapter-page {
        break-before: page;
      }

      .chapter-toc {
        display: none;
      }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#main-content">跳到正文</a>
  <div class="reading-progress" aria-hidden="true">
    <div class="reading-progress-bar" id="readingProgress"></div>
  </div>

  <header class="topbar">
    <div class="topbar-inner">
      <button class="brand-button" type="button" data-page-target="cover" aria-label="返回封面">
        <span class="brand-mark" aria-hidden="true">洛</span>
        <span>AgentLuo</span>
      </button>
      <div class="current-chapter" id="currentChapter">序章</div>
      <button class="menu-button" id="menuButton" type="button" aria-label="打开章节菜单" aria-expanded="false" aria-controls="mobileDrawer">
        <span class="menu-icon" aria-hidden="true"></span>
        <span>章节</span>
      </button>
    </div>
  </header>

  <div class="site-shell">
    <aside class="desktop-nav" aria-label="章节目录">
      <span class="nav-eyebrow">Contents</span>
      ${renderNavItems()}
    </aside>

    <main class="content-stage" id="main-content" tabindex="-1">
      <section class="page cover-page" id="cover" data-page-index="0" aria-labelledby="cover-title">
        <div class="cover-card">
          <span class="cover-eyebrow">Project Plan</span>
          <h1 id="cover-title">${escapeHtml(title)}</h1>
          <span class="cover-rule" aria-hidden="true"></span>
          <p class="cover-quote">${escapeHtml(subtitle)}</p>
          <button class="cover-enter" type="button" data-page-target="${renderedChapters[0]?.id ?? "cover"}">
            开始阅读 <span aria-hidden="true">→</span>
          </button>
        </div>
      </section>

      ${renderedChapters
        .map((chapter, index) => renderChapterPage(chapter, index))
        .join("\n")}
    </main>
  </div>

  <div class="quick-pager" aria-label="章节翻页">
    <button class="pager-button" id="previousPage" type="button" aria-label="上一章">←</button>
    <button class="pager-button" id="nextPage" type="button" aria-label="下一章">→</button>
  </div>

  <button class="drawer-backdrop" id="drawerBackdrop" type="button" aria-label="关闭章节菜单"></button>
  <aside class="mobile-drawer" id="mobileDrawer" aria-label="移动端章节目录" aria-hidden="true">
    <div class="drawer-header">
      <span class="drawer-title">选择章节</span>
      <button class="drawer-close" id="drawerClose" type="button" aria-label="关闭章节菜单">×</button>
    </div>
    <nav class="drawer-nav">
      ${renderNavItems("drawer-link")}
    </nav>
  </aside>

  <div class="page-announcer" id="pageAnnouncer" aria-live="polite"></div>

  <script>
    (() => {
      const pageData = ${pagesJson};
      const pages = Array.from(document.querySelectorAll(".page"));
      const chapterLinks = Array.from(document.querySelectorAll(".chapter-link"));
      const progress = document.getElementById("readingProgress");
      const currentChapter = document.getElementById("currentChapter");
      const previousButton = document.getElementById("previousPage");
      const nextButton = document.getElementById("nextPage");
      const menuButton = document.getElementById("menuButton");
      const drawer = document.getElementById("mobileDrawer");
      const drawerClose = document.getElementById("drawerClose");
      const drawerBackdrop = document.getElementById("drawerBackdrop");
      const announcer = document.getElementById("pageAnnouncer");
      let activeIndex = 0;

      const pageIndexById = new Map(pageData.map((page, index) => [page.id, index]));

      function closeDrawer() {
        document.body.classList.remove("drawer-open");
        menuButton.setAttribute("aria-expanded", "false");
        menuButton.setAttribute("aria-label", "打开章节菜单");
        drawer.setAttribute("aria-hidden", "true");
      }

      function openDrawer() {
        document.body.classList.add("drawer-open");
        menuButton.setAttribute("aria-expanded", "true");
        menuButton.setAttribute("aria-label", "关闭章节菜单");
        drawer.setAttribute("aria-hidden", "false");
        const current = drawer.querySelector('[aria-current="page"]');
        window.setTimeout(() => (current ?? drawerClose).focus(), 180);
      }

      function updateProgress() {
        if (activeIndex === 0) {
          progress.style.width = "0%";
          return;
        }

        const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
        const localProgress = Math.min(1, Math.max(0, window.scrollY / maxScroll));
        const chapterCount = Math.max(1, pageData.length - 1);
        const total = ((activeIndex - 1 + localProgress) / chapterCount) * 100;
        progress.style.width = total.toFixed(2) + "%";
      }

      function updatePager() {
        previousButton.disabled = activeIndex <= 0;
        nextButton.disabled = activeIndex >= pages.length - 1;
        const previous = pageData[activeIndex - 1];
        const next = pageData[activeIndex + 1];
        previousButton.setAttribute(
          "aria-label",
          previous ? "上一章：" + previous.title : "没有上一章",
        );
        nextButton.setAttribute(
          "aria-label",
          next ? "下一章：" + next.title : "没有下一章",
        );
      }

      function showPage(target, options = {}) {
        const targetIndex =
          typeof target === "number" ? target : pageIndexById.get(target);
        if (targetIndex == null || targetIndex < 0 || targetIndex >= pages.length) {
          return;
        }

        activeIndex = targetIndex;
        pages.forEach((page, index) => {
          page.hidden = index !== activeIndex;
          page.classList.remove("page-entering");
        });

        const activePageElement = pages[activeIndex];
        void activePageElement.offsetWidth;
        activePageElement.classList.add("page-entering");

        chapterLinks.forEach((link) => {
          const isCurrent = Number(link.dataset.pageIndex) === activeIndex;
          if (isCurrent) {
            link.setAttribute("aria-current", "page");
          } else {
            link.removeAttribute("aria-current");
          }
        });

        const activePage = pageData[activeIndex];
        currentChapter.textContent = activePage.title;
        document.title =
          activeIndex === 0
            ? ${JSON.stringify(title)}
            : activePage.title + " · " + ${JSON.stringify(title)};
        announcer.textContent = "已进入" + activePage.title;
        updatePager();
        closeDrawer();

        if (!options.preserveScroll) {
          window.scrollTo({ top: 0, behavior: options.instant ? "auto" : "smooth" });
        }

        const newHash = "#" + activePage.id;
        if (window.location.hash !== newHash) {
          history.pushState({ page: activePage.id }, "", newHash);
        }

        window.requestAnimationFrame(updateProgress);
      }

      document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-page-target]");
        if (!trigger) return;
        event.preventDefault();
        showPage(trigger.dataset.pageTarget);
      });

      document.querySelectorAll("[data-subsection-link]").forEach((link) => {
        link.addEventListener("click", (event) => {
          event.preventDefault();
          const target = document.querySelector(link.getAttribute("href"));
          target?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      });

      previousButton.addEventListener("click", () => showPage(activeIndex - 1));
      nextButton.addEventListener("click", () => showPage(activeIndex + 1));
      menuButton.addEventListener("click", () => {
        if (document.body.classList.contains("drawer-open")) closeDrawer();
        else openDrawer();
      });
      drawerClose.addEventListener("click", closeDrawer);
      drawerBackdrop.addEventListener("click", closeDrawer);

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          closeDrawer();
          return;
        }

        const tag = document.activeElement?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;

        if (event.key === "ArrowLeft") {
          showPage(activeIndex - 1);
        } else if (event.key === "ArrowRight") {
          showPage(activeIndex + 1);
        }
      });

      window.addEventListener("scroll", updateProgress, { passive: true });
      window.addEventListener("resize", updateProgress);
      window.addEventListener("popstate", () => {
        const id = window.location.hash.slice(1);
        showPage(pageIndexById.has(id) ? id : "cover", {
          instant: true,
          preserveScroll: false,
        });
      });

      const initialId = window.location.hash.slice(1);
      showPage(pageIndexById.has(initialId) ? initialId : "cover", {
        instant: true,
      });
      history.replaceState(
        { page: pageData[activeIndex].id },
        "",
        "#" + pageData[activeIndex].id,
      );
    })();
  </script>

  <!-- Generated from AgentLuo项目计划书.md at ${generatedAt}. -->
</body>
</html>
`;

fs.writeFileSync(indexPath, html, "utf8");
fs.writeFileSync(namedHtmlPath, html, "utf8");

console.log(`Generated ${path.basename(indexPath)} and ${path.basename(namedHtmlPath)}`);
console.log(`Chapters: ${renderedChapters.length}; pages including cover: ${allPages.length}`);
