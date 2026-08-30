import type { Metadata } from 'next';
import './(default)/css/globals.css';

/**
 * Local fork note (why we don't use `next/font/google` here):
 *
 * Building this app inside the Docker builder repeatedly failed with
 *   `Failed to fetch <URL> from Google Fonts` on Space_Grotesk / Geist /
 *   Noto_Sans_{SC,KR,JP}
 * — the builder network can't reliably reach fonts.googleapis.com at compile
 * time. Rather than depend on that fetch every rebuild, we now bind the CSS
 * variables the rest of the app expects (`--font-geist`, `--font-space-grotesk`,
 * `--font-noto-sans-{sc,kr,jp}`) to system font stacks. On the DESKTOP browser
 * the visible faces are slightly different (system UI faces instead of Geist /
 * Space Grotesk), which is fine — the resume-render pipeline picks its own
 * font (see FONT_FAMILY_META in lib/types/template-settings.ts), and CJK
 * content still renders correctly because the container installs
 * `fonts-noto-cjk` as system fonts (see Dockerfile).
 */
const FONT_VARIABLE_STYLES: React.CSSProperties = {
  // Two branded faces the app's Tailwind config references — remapped to a
  // reasonable system stack. Users who want Geist/Space Grotesk can host them
  // themselves and swap these values.
  ['--font-geist' as string]:
    'ui-sans-serif, system-ui, "Inter", "Helvetica Neue", Arial, sans-serif',
  ['--font-space-grotesk' as string]:
    '"Space Grotesk", ui-sans-serif, system-ui, "Inter", Arial, sans-serif',
  // CJK variables — bind directly to installed Noto CJK families so the
  // per-locale stack in template-settings.ts still resolves correctly. On
  // desktop browsers without these installed, the browser falls through to
  // its own CJK support (macOS ships PingFang/Hiragino, Windows ships MS
  // Gothic, etc.), so nothing appears as tofu.
  ['--font-noto-sans-sc' as string]:
    '"Noto Sans SC", "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  ['--font-noto-sans-jp' as string]:
    '"Noto Sans JP", "Noto Sans CJK JP", "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif',
  ['--font-noto-sans-kr' as string]:
    '"Noto Sans KR", "Noto Sans CJK KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif',
};

export const metadata: Metadata = {
  title: 'Resume Matcher',
  description: 'Build your resume with Resume Matcher',
  applicationName: 'Resume Matcher',
  keywords: ['resume', 'matcher', 'job', 'application'],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-US" className="h-full" suppressHydrationWarning style={FONT_VARIABLE_STYLES}>
      <body className="antialiased bg-background text-ink-soft min-h-full">{children}</body>
    </html>
  );
}
