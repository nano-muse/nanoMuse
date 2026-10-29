// The nanoMuse docs site: VitePress over ../docs. Nothing is copied — the pages under
// docs/ are the source, and this file only says how they are arranged and where the
// links that leave docs/ go.
//
//   npm run docs:dev      # http://127.0.0.1:5173/<base>
//   npm run docs:build    # .vitepress/dist, also the dead-link check
//   DOCS_BASE=/docs/ npm run docs:build   # for nanomuse.cn/docs/
//
// DOCS_BASE defaults to /nanoMuse/docs/ — the project pages at nano-muse.github.io keep
// site/index.html (the redirect to nanomuse.cn) and site/legacy.html at the root, and the
// docs sit beside them under /docs/.
import { posix } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, type DefaultTheme } from 'vitepress'

const REPO = 'https://github.com/nano-muse/nanoMuse'
const base = process.env.DOCS_BASE ?? '/nanoMuse/docs/'

// Directories under docs/ that are not pages of the site: task briefs and traces are
// working notes, the archive is the Python line's record, the release notes and the
// translated READMEs are read on GitHub. Links into them become GitHub links. The pages
// in notPages stay in the repository but are not on the site either: the two templates,
// and calls.md, the record of a feature removed in 0.1.22.
const notOnTheSite = ['tasks/', 'archive/', 'traces/', 'briefs/', 'releases/', 'readme/']
const notPages = ['release-notes-template.md', 'launch-checklist.md', 'calls.md']

// The site's languages: the English pages are docs/*.md, the Chinese ones docs/zh/*.md
// with the same file names. A page link (`android.md`) stays inside the reader's language;
// everything else — images, the archive, the repository — is shared and lives one level up
// from docs/zh/, which is why the Chinese pages write `../screenshots/x.png` and
// `../../nanomuse/config.py`.
const localeDirs = ['zh/']

/** `../nanomuse/config.py` from docs/cloud.md → a GitHub URL; a docs page stays a docs link. */
function githubFor(href: string, fromPage: string): string | undefined {
  if (/^([a-z]+:|\/\/|#)/i.test(href)) return undefined // absolute, mailto:, anchors
  const [path, rest = ''] = href.split(/(?=[#?])/, 2)
  if (!path) return undefined
  const inDocs = posix.normalize(posix.join(posix.dirname(fromPage), path))
  if (inDocs.startsWith('../')) {
    const inRepo = posix.normalize(posix.join('docs', inDocs))
    if (inRepo.startsWith('../')) return undefined
    const kind = inRepo.endsWith('/') || !posix.extname(inRepo) ? 'tree' : 'blob'
    return `${REPO}/${kind}/main/${inRepo}${rest}`
  }
  // `zh/calls.md` is the same excluded page as `calls.md`; there is no Chinese twin of a
  // page that is not on the site, so the GitHub link goes to the English file.
  const localeDir = localeDirs.find((d) => inDocs.startsWith(d)) ?? ''
  const inLocale = inDocs.slice(localeDir.length)
  const excluded = notOnTheSite.some((d) => inLocale.startsWith(d)) || notPages.includes(inLocale)
  const notMarkdown = posix.extname(inDocs) !== '' && posix.extname(inDocs) !== '.md'
  const directory = inDocs.endsWith('/') || posix.extname(inDocs) === ''
  if (excluded || notMarkdown || directory) {
    const kind = directory ? 'tree' : 'blob'
    const target = excluded ? inLocale : inDocs
    return `${REPO}/${kind}/main/docs/${target}${rest}`
  }
  return undefined
}

// Vue reads `{{ … }}` in page text as an expression; the docs mean it literally
// (`{{vault:NAME}}`). Fences are already left alone by VitePress.
const literal = (html: string) => html.replaceAll('{{', '&#123;&#123;').replaceAll('}}', '&#125;&#125;')

// `<host>` or `<version>` in prose is a placeholder, not an element; Vue would want it closed.
// Real HTML in the pages (images, details, line breaks) passes through.
const htmlTags = new Set(['a', 'abbr', 'b', 'br', 'code', 'details', 'div', 'em', 'figcaption', 'figure', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'iframe', 'img', 'kbd', 'li', 'ol', 'p', 'picture', 'pre', 'source', 'span', 'strong', 'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'u', 'ul', 'video'])
const bare = /^([a-z]+:|\/\/|\/|\.\.?\/|#)/i
const explicitSrc = (html: string) => html.replace(/(<img\b[^>]*\bsrc=")([^"]+)(")/g, (_, pre, src, post) => `${pre}${bare.test(src) ? src : `./${src}`}${post}`)
function placeholderOrHtml(raw: string): string {
  const tag = /^<\/?([a-zA-Z][\w-]*)/.exec(raw)?.[1]?.toLowerCase()
  if (raw.startsWith('<!--') || (tag && htmlTags.has(tag))) return explicitSrc(raw)
  return raw.replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

const getStarted: DefaultTheme.SidebarItem[] = [
  { text: 'Android', link: '/android' },
  { text: 'iPhone and iPad', link: '/ios' },
  { text: 'The desktop app', link: '/desktop' },
  { text: 'The web console', link: '/web' },
  { text: 'One account, all your devices', link: '/trial' },
  { text: 'Your own model key', link: '/own-key' },
  { text: 'Troubleshooting', link: '/troubleshooting' },
]

const useIt: DefaultTheme.SidebarItem[] = [
  { text: 'Every device', link: '/every-device' },
  { text: 'The screen as a hand', link: '/gui' },
  { text: 'Computer use, on the desktop', link: '/desktop-muse#computer-use' },
  { text: 'Feed, Ideas, Goals, Library', link: '/desktop-muse#rail-rooms' },
  { text: 'Memory and goals from the terminal', link: '/cli' },
  { text: 'Connectors', link: '/configuration#connectors' },
  { text: 'Chat apps: Feishu, DingTalk, WeCom, Telegram', link: '/channels' },
  { text: 'Coding agents', link: '/coding-agents' },
  { text: 'The avatar studio', link: '/avatar' },
  { text: 'The browser', link: '/browser' },
  { text: 'Chinese services without a screen', link: '/services' },
  { text: 'The showcase', link: '/showcase' },
]

const runIt: DefaultTheme.SidebarItem[] = [
  { text: 'Run nanoMuse yourself', link: '/self-hosting' },
  { text: 'The runtime in Docker', link: '/deployment' },
  { text: 'Configuration', link: '/configuration' },
  { text: 'Task budgets', link: '/runtime-budgets' },
  { text: 'nanoMuse Cloud, the relay', link: '/cloud' },
]

const understandIt: DefaultTheme.SidebarItem[] = [
  { text: 'Architecture', link: '/architecture' },
  { text: 'Sentinel', link: '/sentinel' },
  { text: 'Privacy', link: '/privacy' },
  { text: 'What stays on a phone, and whose it is', link: '/sync' },
  { text: 'The hub', link: '/hub' },
  { text: 'Design: how it looks, and why', link: '/design' },
  { text: 'nanoMuse on DeepSeek Harness', link: '/harness' },
  { text: 'The phone’s own capabilities', link: '/device' },
  { text: 'The app, as designed', link: '/app' },
  { text: 'The local runtime on the phone', link: '/local-runtime' },
  { text: 'Brand', link: '/brand' },
]

const contribute: DefaultTheme.SidebarItem[] = [
  { text: 'Contributing', link: `${REPO}/blob/main/CONTRIBUTING.md` },
  { text: 'AGENTS.md', link: `${REPO}/blob/main/AGENTS.md` },
  { text: 'README', link: `${REPO}/blob/main/README.md` },
  { text: 'Roadmap', link: '/roadmap' },
  { text: 'Parity between the clients', link: '/parity' },
  { text: 'Release notes', link: `${REPO}/releases` },
  { text: 'Changelog', link: `${REPO}/blob/main/CHANGELOG.md` },
]

// The same pages in Chinese, under /zh/. The group and item names follow what the apps'
// Chinese screens call things (CONTRIBUTING.md, "Translating the docs", has the glossary).
const zhGetStarted: DefaultTheme.SidebarItem[] = [
  { text: 'Android', link: '/zh/android' },
  { text: 'iPhone 和 iPad', link: '/zh/ios' },
  { text: '桌面版', link: '/zh/desktop' },
  { text: '网页控制台', link: '/zh/web' },
  { text: '一个账号，所有设备', link: '/zh/trial' },
  { text: '自己的模型 key', link: '/zh/own-key' },
  { text: '故障排查', link: '/zh/troubleshooting' },
]

const zhUseIt: DefaultTheme.SidebarItem[] = [
  { text: '每一台设备', link: '/zh/every-device' },
  { text: '「手」：把屏幕当手用', link: '/zh/gui' },
  { text: '桌面版的电脑操作', link: '/zh/desktop-muse#computer-use' },
  { text: '动态、点子、目标、资源库', link: '/zh/desktop-muse#rail-rooms' },
  { text: '终端里的记忆和目标', link: '/zh/cli' },
  { text: '连接器', link: '/zh/configuration#connectors' },
  { text: '聊天入口：飞书、钉钉、企业微信、Telegram', link: '/zh/channels' },
  { text: '编程助手', link: '/zh/coding-agents' },
  { text: '形象工作室', link: '/zh/avatar' },
  { text: '浏览器', link: '/zh/browser' },
  { text: '不走屏幕的中文服务', link: '/zh/services' },
  { text: '展示站', link: '/zh/showcase' },
]

const zhRunIt: DefaultTheme.SidebarItem[] = [
  { text: '自己运行 nanoMuse', link: '/zh/self-hosting' },
  { text: 'Docker 里的运行时', link: '/zh/deployment' },
  { text: '配置', link: '/zh/configuration' },
  { text: '任务预算', link: '/zh/runtime-budgets' },
  { text: 'nanoMuse Cloud：中继', link: '/zh/cloud' },
]

const zhUnderstandIt: DefaultTheme.SidebarItem[] = [
  { text: '架构', link: '/zh/architecture' },
  { text: '哨兵（Sentinel）', link: '/zh/sentinel' },
  { text: '隐私', link: '/zh/privacy' },
  { text: '什么留在手机上，归谁', link: '/zh/sync' },
  { text: 'hub：设备互联', link: '/zh/hub' },
  { text: '设计：长什么样，为什么', link: '/zh/design' },
  { text: 'DeepSeek Harness 上的 nanoMuse', link: '/zh/harness' },
  { text: '手机自身的能力', link: '/zh/device' },
  { text: '手机 App 的设计', link: '/zh/app' },
  { text: '手机上的本地运行时', link: '/zh/local-runtime' },
  { text: '品牌', link: '/zh/brand' },
]

const zhContribute: DefaultTheme.SidebarItem[] = [
  { text: '参与贡献（英文）', link: `${REPO}/blob/main/CONTRIBUTING.md` },
  { text: 'AGENTS.md（英文）', link: `${REPO}/blob/main/AGENTS.md` },
  { text: '中文 README', link: `${REPO}/blob/main/docs/readme/README_zh.md` },
  { text: '路线图', link: '/zh/roadmap' },
  { text: '各客户端的功能对照', link: '/zh/parity' },
  { text: '发布说明', link: `${REPO}/releases` },
  { text: '更新日志', link: `${REPO}/blob/main/CHANGELOG.md` },
]

export default defineConfig({
  title: 'nanoMuse',
  description: 'An open-source personal agent for every device you own.',
  lang: 'en',
  base,
  srcDir: '../docs',
  srcExclude: ['tasks/**', 'archive/**', 'traces/**', 'briefs/**', 'releases/**', 'readme/**', ...notPages],
  cleanUrls: true,
  lastUpdated: false,
  // One site, two languages. `root` is English at /, `zh` is 简体中文 at /zh/ with the same
  // file names under docs/zh/. Nav, sidebar, search, footer and the edit link are per
  // locale; the language menu in the nav is VitePress's own.
  locales: {
    root: {
      label: 'English',
      lang: 'en',
      themeConfig: {
        siteTitle: 'nanoMuse docs',
        // Home and Try it are the project site and the demo, the same two the homepage's bar has.
        nav: [
          { text: 'Home', link: 'https://nanomuse.cn/' },
          { text: 'Try it', link: 'https://demo.nanomuse.dev/' },
          { text: 'Get started', link: '/android' },
          { text: 'Run it yourself', link: '/self-hosting' },
          { text: 'Roadmap', link: '/roadmap' },
        ],
        sidebar: [
          { text: 'Get started', items: getStarted },
          { text: 'Use it', items: useIt },
          { text: 'Run it yourself', items: runIt },
          { text: 'Understand it', collapsed: true, items: understandIt },
          { text: 'Contribute', collapsed: true, items: contribute },
        ],
        outline: { level: [2, 3], label: 'On this page' },
        editLink: { pattern: `${REPO}/edit/main/docs/:path`, text: 'Edit this page on GitHub' },
        footer: {
          message: 'GPL-3.0-or-later. nanoMuse is an independent community project, not affiliated with Meta.',
          copyright: 'The nanoMuse contributors',
        },
        langMenuLabel: 'Change language',
      },
    },
    zh: {
      label: '简体中文',
      lang: 'zh-Hans',
      link: '/zh/',
      title: 'nanoMuse',
      description: '开源的个人智能体，面向你的每一台设备。',
      themeConfig: {
        siteTitle: 'nanoMuse 文档',
        nav: [
          { text: '首页', link: 'https://nanomuse.cn/' },
          { text: '试一试', link: 'https://demo.nanomuse.dev/' },
          { text: '上手', link: '/zh/android' },
          { text: '自己部署', link: '/zh/self-hosting' },
          { text: '路线图', link: '/zh/roadmap' },
        ],
        sidebar: [
          { text: '上手', items: zhGetStarted },
          { text: '使用', items: zhUseIt },
          { text: '自己部署', items: zhRunIt },
          { text: '理解它', collapsed: true, items: zhUnderstandIt },
          { text: '参与', collapsed: true, items: zhContribute },
        ],
        outline: { level: [2, 3], label: '本页目录' },
        docFooter: { prev: '上一页', next: '下一页' },
        editLink: { pattern: `${REPO}/edit/main/docs/:path`, text: '在 GitHub 上编辑此页' },
        lastUpdatedText: '最后更新',
        darkModeSwitchLabel: '外观',
        lightModeSwitchTitle: '切换到浅色',
        darkModeSwitchTitle: '切换到深色',
        sidebarMenuLabel: '目录',
        returnToTopLabel: '回到顶部',
        langMenuLabel: '切换语言',
        skipToContentLabel: '跳到正文',
        notFound: {
          title: '没有这一页',
          quote: '地址可能打错了，或者这一页已经搬走。',
          linkLabel: '回到文档首页',
          linkText: '回到文档首页',
          code: '404',
        },
        footer: {
          message: 'GPL-3.0-or-later。nanoMuse 是独立的社区项目，与 Meta 无关。',
          copyright: 'nanoMuse 贡献者',
        },
      },
    },
  },
  // Vite's root is srcDir, which has no node_modules above it; point `vue` at ours. The
  // public dir is website/public (the icon, copied from assets/brand/), so nothing on the
  // site is fetched from a host a reader in China cannot reach.
  vite: {
    publicDir: fileURLToPath(new URL('../public', import.meta.url)),
    resolve: { alias: [{ find: /^vue(\/.*)?$/, replacement: `${fileURLToPath(new URL('../node_modules/vue', import.meta.url))}$1` }] },
  },
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}nanomuse-icon.svg` }],
  ],
  // Internal links are checked at build time. The link_open rule below turns every link that
  // leaves docs/ into a GitHub URL, so nothing should remain here; add a pattern only for a
  // code link the rule cannot resolve.
  ignoreDeadLinks: [],
  markdown: {
    config(md) {
      const renderText = md.renderer.rules.text!
      const renderCode = md.renderer.rules.code_inline!
      md.renderer.rules.text = (...args) => literal(renderText(...args))
      md.renderer.rules.code_inline = (...args) => literal(renderCode(...args))
      md.renderer.rules.html_inline = (tokens, idx) => literal(placeholderOrHtml(tokens[idx].content))
      md.renderer.rules.html_block = (tokens, idx, _options, env) => {
        const raw = tokens[idx].content
        const tag = /^<\/?([a-zA-Z][\w-]*)/.exec(raw)?.[1]?.toLowerCase()
        if (raw.startsWith('<!--') || (tag && htmlTags.has(tag))) return explicitSrc(raw)
        // a paragraph that happens to start with a placeholder: render it as prose
        return `<p>${md.renderInline(raw.trimEnd(), env)}</p>\n`
      }
      // `![](screenshots/x.png)` is a relative path to markdown; to Vite a bare specifier is a
      // package. Make the relative form explicit so the picture is bundled.
      const renderImage = md.renderer.rules.image!
      md.renderer.rules.image = (tokens, idx, options, env, self) => {
        const src = tokens[idx].attrGet('src')
        if (src && !/^([a-z]+:|\/\/|\/|\.\.?\/)/i.test(src)) tokens[idx].attrSet('src', `./${src}`)
        return renderImage(tokens, idx, options, env, self)
      }
      const renderLink = md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
      md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
        const token = tokens[idx]
        const href = token.attrGet('href')
        const page: string | undefined = env?.relativePath
        if (href && page) {
          const github = githubFor(href, page)
          if (github) {
            token.attrSet('href', github)
            token.attrSet('target', '_blank')
            token.attrSet('rel', 'noreferrer')
          }
        }
        return renderLink(tokens, idx, options, env, self)
      }
    },
  },
  // What both languages share. GitHub is not in socialLinks: the nav shows it with the
  // star count instead (theme/GitHubStars.vue, the `nav-bar-content-after` slot).
  themeConfig: {
    logo: '/nanomuse-icon.svg',
    socialLinks: [
      { icon: 'discord', link: 'https://discord.gg/bkTySmm28X' },
    ],
    search: {
      provider: 'local',
      options: {
        locales: {
          zh: {
            translations: {
              button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
              modal: {
                displayDetails: '显示详细列表',
                resetButtonTitle: '清空',
                backButtonTitle: '关闭搜索',
                noResultsText: '没有找到',
                footer: {
                  selectText: '打开',
                  selectKeyAriaLabel: '回车',
                  navigateText: '上下移动',
                  navigateUpKeyAriaLabel: '上箭头',
                  navigateDownKeyAriaLabel: '下箭头',
                  closeText: '关闭',
                  closeKeyAriaLabel: 'Esc',
                },
              },
            },
          },
        },
      },
    },
  },
})
