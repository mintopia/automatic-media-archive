export const SECTIONS = [
  {
    label: "Get started",
    pages: [
      { slug: "install", title: "Install" },
      { slug: "setup", title: "Setup walkthrough" },
    ],
  },
  {
    label: "How it works",
    pages: [
      { slug: "how-a-disc-flows", title: "How a Disc flows" },
      { slug: "libraries", title: "Libraries & Naming Patterns" },
    ],
  },
  {
    label: "Reference",
    pages: [
      { slug: "settings", title: "Settings reference" },
      { slug: "third-party", title: "Third-party tools & licences" },
      { slug: "contributing", title: "Contributing" },
    ],
  },
] as const;

export type Section = (typeof SECTIONS)[number];
export type Page = Section["pages"][number];
export type Slug = Page["slug"];

export const PAGES: readonly Page[] = SECTIONS.flatMap<Page>((s) => s.pages);

export function sectionOf(slug: Slug): Section {
  return SECTIONS.find((s) => s.pages.some((p) => p.slug === slug))!;
}

export function neighbours(slug: Slug): { prev?: Page; next?: Page } {
  const i = PAGES.findIndex((p) => p.slug === slug);
  return { prev: PAGES[i - 1], next: PAGES[i + 1] };
}
