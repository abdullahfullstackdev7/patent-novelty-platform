export interface ArticleSection {
  heading?: string;
  paragraphs?: string[];
  bullets?: string[];
}

export interface Article {
  slug: string;
  title: string;
  summary: string;
  readMinutes: number;
  published: string;
  sections: ArticleSection[];
}

export const ARTICLES: Article[] = [
  {
    slug: "guide-to-prior-art-searching",
    title: "A practical guide to prior-art searching",
    summary: "How to move from an invention disclosure to a defensible set of references, and when to stop.",
    readMinutes: 3,
    published: "2026-09-02",
    sections: [
      {
        paragraphs: [
          "Prior art is anything made available to the public before the effective filing date of a claimed invention that could bear on whether the invention is new and non-obvious. It includes granted patents and published applications, but also journal papers, product manuals, conference talks and public web pages. A good search is less about finding one decisive document and more about building a record that shows you looked in the right places.",
        ],
      },
      {
        heading: "Start from the claims, not the title",
        paragraphs: [
          "A disclosure usually describes a preferred embodiment. The claims define what is actually being protected, and they are what references are measured against. Break each claim into its elements: the components, the steps and the relationships between them. Write each element as a short, neutral phrase. This list becomes both your search plan and, later, the rows of a claim chart.",
        ],
      },
      {
        heading: "Use more than one kind of query",
        paragraphs: [
          "Keyword searches are precise but brittle, because different authors name the same thing differently. A battery thermal sensor may appear as a temperature probe, a thermistor or a heat detector. Semantic search compares meaning rather than spelling and tends to recover those variants. Classification searches add a third angle: the Cooperative Patent Classification groups documents by technical subject, so a strong hit in one class points you to its neighbours.",
        ],
        bullets: [
          "Run keyword queries for exact terms and defined phrases.",
          "Run semantic queries using the element descriptions in your own words.",
          "Follow citations forward and backward from your best references.",
          "Search the classes where the best references cluster.",
        ],
      },
      {
        heading: "Record what you did",
        paragraphs: [
          "A search is only as useful as it is reproducible. Keep the queries, the databases, the date and the number of results reviewed. If a reference is dropped, note why. Months later, when someone asks whether a particular document was considered, the record answers the question in seconds.",
        ],
      },
      {
        heading: "Knowing when to stop",
        paragraphs: [
          "Searching has diminishing returns. A reasonable stopping point is when new queries keep returning documents you have already seen, and when the closest references cover each claim element at least once or clearly do not. If one element remains uncovered after varied queries, that gap is itself a finding, and it is worth stating plainly in your opinion.",
          "No automated tool can promise that nothing was missed. What a good tool can do is widen the net, organise the results around your claim elements and show its evidence, so that the person making the judgment spends their time reasoning rather than collecting.",
        ],
      },
    ],
  },
  {
    slug: "understanding-claim-charts",
    title: "Understanding claim charts",
    summary: "What a claim chart is, how to read one, and what makes a chart trustworthy.",
    readMinutes: 3,
    published: "2026-09-16",
    sections: [
      {
        paragraphs: [
          "A claim chart is a table that compares a patent claim, element by element, with a piece of evidence. In a prior-art setting the evidence is a reference, and the chart shows which parts of the claim that reference discloses. Charts are used in novelty opinions, invalidity contentions and freedom-to-operate reviews because they make an argument checkable at a glance.",
        ],
      },
      {
        heading: "The anatomy of a chart",
        paragraphs: [
          "The left column lists the claim elements in order. Each remaining column represents one reference. A cell holds two things: a rating of how well the reference covers the element, and the passage that supports the rating. The passage matters more than the rating. A reader should be able to look at the quoted text and agree or disagree for themselves.",
        ],
        bullets: [
          "Disclosed: the reference describes the element, expressly or inherently.",
          "Partial: the reference describes something close but not the whole element.",
          "Absent: the reference does not address the element.",
        ],
      },
      {
        heading: "Reading across and down",
        paragraphs: [
          "Reading down a column tells you how much of the claim a single reference covers. For novelty, a single reference must disclose every element, so one column full of disclosed cells is a serious finding. Reading across a row tells you how widely an element is known. An element that appears in every reference is probably conventional, while an element that no reference covers is where the claim's real contribution may sit.",
        ],
      },
      {
        heading: "What makes a chart trustworthy",
        paragraphs: [
          "The first test is verbatim evidence. Every quoted passage should appear exactly in the source, with a location a reviewer can find. Paraphrase invites dispute and hides errors. The second test is consistency: the same words in two elements should be rated the same way across references. The third test is honesty about gaps, meaning that an absent cell is shown as absent instead of being filled with a stretched reading.",
          "Charts generated with the help of language models deserve extra care. Models can write fluent summaries of passages that do not say what the summary claims. That is why a platform should check each excerpt against the original text and reject any that cannot be matched.",
        ],
      },
      {
        heading: "A chart is a starting point",
        paragraphs: [
          "Even a well-built chart does not decide anything. Whether a feature is disclosed inherently, or whether a partial match would have been obvious, are legal judgments. The chart organises the facts so that the attorney can make those judgments efficiently and explain them clearly.",
        ],
      },
    ],
  },
  {
    slug: "novelty-versus-obviousness",
    title: "Novelty versus obviousness: two tests, two questions",
    summary: "Why a claim can be new and still unpatentable, and how the two tests differ in practice.",
    readMinutes: 3,
    published: "2026-09-30",
    sections: [
      {
        paragraphs: [
          "Patentability has several requirements, and two of them are often confused: novelty and non-obviousness. They are separate tests that ask different questions and use prior art in different ways. A claim can pass one and fail the other, so a sound prior-art review addresses both.",
        ],
      },
      {
        heading: "Novelty asks: has it been done?",
        paragraphs: [
          "Under United States law, a claim lacks novelty if a single prior-art reference discloses every element of the claim, arranged as claimed. The test is strict and narrow. If the reference is missing even one element, the claim is not anticipated by that reference. This is why claim charts are organised element by element and why one column full of disclosed cells is so significant.",
        ],
      },
      {
        heading: "Obviousness asks: would it have been an easy step?",
        paragraphs: [
          "A claim can be new and still be obvious. The question is whether a person of ordinary skill in the field, knowing the prior art, would have found the claimed invention an obvious step. Here the examiner or attorney may combine several references, and may rely on common knowledge, provided there is a reason to combine them and a reasonable expectation of success.",
        ],
        bullets: [
          "Novelty uses one reference and requires every element.",
          "Obviousness may use several references and asks about motivation.",
          "Novelty is a factual comparison. Obviousness involves judgment about skill and reasoning.",
        ],
      },
      {
        heading: "How the two show up in a review",
        paragraphs: [
          "When a single reference covers most elements, novelty risk is high. When no single reference covers everything but two or three together cover all elements and sit in the same technical area, obviousness risk rises. The strongest position for an applicant is a claim with at least one element that no reference covers and that gives a clear technical effect.",
          "A transparent tool makes these relationships visible. It should show which elements each reference covers, which remain uncovered, and how that translates into a risk level. It should also state that the level is an input to professional judgment and that it does not replace that judgment.",
        ],
      },
      {
        heading: "Practical takeaway",
        paragraphs: [
          "Ask the two questions in order. First, does any single reference disclose the whole claim? Then, if not, could a handful of references combine to reach it, and would a skilled person have had a reason to combine them? Writing the answers down, with the supporting passages, turns a hunch into an opinion that others can examine and rely on. It also makes the next review easier, because anyone picking up the file can see which references mattered and why.",
        ],
      },
    ],
  },
];

export const articleText = (article: Article): string =>
  article.sections
    .flatMap((s) => [s.heading ?? "", ...(s.paragraphs ?? []), ...(s.bullets ?? [])])
    .join(" ");

export const findArticle = (slug: string | undefined) => ARTICLES.find((a) => a.slug === slug);
