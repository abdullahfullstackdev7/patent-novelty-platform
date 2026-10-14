import {
  BarChart3,
  BookOpenCheck,
  ClipboardCheck,
  FileInput,
  FileSearch,
  Gauge,
  Quote,
  Search,
  Table2,
  Users,
  type LucideIcon,
} from "lucide-react";

export interface NavLink {
  label: string;
  to: string;
  description?: string;
}

export const NAV = {
  platform: [
    { label: "Platform overview", to: "/platform", description: "Search, charting, risk scoring and review in one workflow" },
    { label: "Hybrid search", to: "/platform#search", description: "Semantic and keyword retrieval over US patent text" },
    { label: "Claim charts", to: "/platform#charts", description: "Element-by-element comparison with verbatim evidence" },
    { label: "Reports and review", to: "/platform#review", description: "Attorney sign-off and exportable reports" },
  ] satisfies NavLink[],
  solutions: [
    { label: "Patent attorneys", to: "/solutions#attorneys", description: "Faster, better-evidenced novelty opinions" },
    { label: "Corporate IP counsel", to: "/solutions#corporate", description: "Consistent screening across invention disclosures" },
    { label: "R&D and innovation", to: "/solutions#rnd", description: "Check an idea before the lab invests in it" },
    { label: "Universities", to: "/solutions#universities", description: "Triage disclosures for tech transfer" },
  ] satisfies NavLink[],
  resources: [
    { label: "All resources", to: "/resources", description: "Guides on prior-art search and patentability" },
    { label: "Prior-art searching", to: "/resources/guide-to-prior-art-searching", description: "A practical guide" },
    { label: "Claim charts", to: "/resources/understanding-claim-charts", description: "What they are and how to read them" },
    { label: "Novelty and obviousness", to: "/resources/novelty-versus-obviousness", description: "Two tests, two questions" },
  ] satisfies NavLink[],
  company: [
    { label: "About us", to: "/about", description: "Mission, values and team" },
    { label: "Security", to: "/security", description: "How customer data is protected" },
    { label: "Contact", to: "/contact", description: "Talk to the team" },
  ] satisfies NavLink[],
};

export const FOOTER_COLUMNS: { title: string; links: NavLink[] }[] = [
  { title: "Platform", links: NAV.platform },
  { title: "Solutions", links: NAV.solutions },
  { title: "Resources", links: NAV.resources },
  { title: "Company", links: [...NAV.company.filter((l) => l.to !== "/security"), { label: "Pricing", to: "/pricing" }] },
  {
    title: "Legal",
    links: [
      { label: "Privacy Policy", to: "/legal/privacy" },
      { label: "Terms of Use", to: "/legal/terms" },
      { label: "Cookie Notice", to: "/legal/cookies" },
      { label: "Accessibility Statement", to: "/legal/accessibility" },
      { label: "Security", to: "/security" },
    ],
  },
];

export const SAMPLE_FIRMS = ["Harlow & Crane LLP", "Northvale IP", "Ostrander Patent Group", "Lindqvist Partners", "Brightwater Legal", "Kestrel IP Counsel"];

export const STEPS: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: FileInput, title: "Disclosure intake", text: "Paste or upload an invention disclosure. Claim elements are extracted and you confirm them." },
  { icon: Search, title: "Semantic search", text: "Hybrid vector and keyword retrieval, reranked, with CPC voting to focus on the right classes." },
  { icon: Table2, title: "Claim charting", text: "Every element is compared with the closest references, with verbatim excerpts as evidence." },
  { icon: Gauge, title: "Risk assessment", text: "Novelty and obviousness risk follow transparent rules, not an opaque score." },
  { icon: ClipboardCheck, title: "Attorney review", text: "Reviewers comment, adjust and sign off. The report records who decided what." },
];

export const CAPABILITIES: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: FileSearch, title: "Semantic and keyword hybrid search", text: "Meaning-based retrieval finds references that use different words for the same idea, while full-text search keeps exact terminology precise." },
  { icon: Table2, title: "Claim chart viewer", text: "A side-by-side grid of your elements against each reference, with a coverage rating and the supporting passage in every cell." },
  { icon: Gauge, title: "Novelty and obviousness risk scoring", text: "Deterministic rules turn coverage into a risk level you can explain to a client, and the rules are shown in the report." },
  { icon: Quote, title: "Verbatim excerpt evidence", text: "Every cited passage is checked against the source text before it is shown. Anything that cannot be matched is rejected." },
  { icon: Users, title: "Collaboration and review workflow", text: "Share cases, assign reviewers, track status and keep an audit trail of every change and sign-off." },
  { icon: BarChart3, title: "Analytics and reporting", text: "Turnaround, technology areas and risk mix across your portfolio, with CSV export for further analysis." },
];

export const TOUR = [
  { id: "search", label: "Search results", title: "Ranked references with the reasons", text: "Results combine semantic and keyword scores, show the matching passages and group by classification so the strongest references surface first.", rows: ["US10234567B2  Adaptive battery thermal controller", "US9876543B2  Cell temperature estimation method", "US11002233B1  Pack cooling manifold"] },
  { id: "chart", label: "Claim chart", title: "Every element against every reference", text: "Coverage is rated per cell as disclosed, partial or absent, always with the excerpt behind the rating.", rows: ["Element 1  a sensor coupled to the cell      Disclosed", "Element 2  a controller configured to ...     Partial", "Element 3  a coolant loop adjacent to ...     Absent"] },
  { id: "report", label: "Risk report", title: "An opinion-ready summary", text: "Novelty and obviousness risk, the closest references and the open questions, versioned and ready for attorney sign-off.", rows: ["Novelty risk        Medium", "Obviousness risk    Low", "Closest reference   US10234567B2"] },
  { id: "analytics", label: "Analytics dashboard", title: "See the portfolio, not just the case", text: "Turnaround time, risk distribution and technology areas across every case your team has run.", rows: ["Cases this quarter       42", "Median turnaround        3 h 40 min", "Most active area         H01M batteries"] },
];

export const SOLUTIONS: { id: string; title: string; summary: string; bullets: string[] }[] = [
  { id: "attorneys", title: "Patent attorneys", summary: "Spend your time on judgment, not on collecting and cross-checking references.", bullets: ["Start every opinion from a charted set of the closest references", "Trace each statement to a verbatim excerpt you can quote", "Record your own review decisions in the report history"] },
  { id: "corporate", title: "Corporate IP counsel", summary: "Screen invention disclosures consistently before outside counsel is engaged.", bullets: ["Apply the same method to every disclosure from every business unit", "Prioritise filings by risk level instead of by submission order", "Keep a searchable record of what was considered and why"] },
  { id: "rnd", title: "R&D and innovation teams", summary: "Find out early whether an idea has been done before.", bullets: ["Get a first read on novelty in minutes, not weeks", "See which technology areas are crowded and which are open", "Hand a clear starting point to counsel when an idea looks promising"] },
  { id: "universities", title: "Universities and tech transfer offices", summary: "Triage a stream of disclosures with a small team.", bullets: ["Rank disclosures by patentability risk to focus scarce budget", "Give inventors an evidence-based explanation, not just a verdict", "Share cases with external counsel without losing control of access"] },
];

export const SECURITY_CONTROLS: { title: string; text: string }[] = [
  { title: "Encryption in transit and at rest", text: "Connections use TLS. Disclosure text, reports and cached model responses are encrypted before they are stored, with keys that can be rotated." },
  { title: "Role-based access", text: "Four roles (administrator, attorney, analyst, viewer) with server-side checks on every request. Cases a user may not see are indistinguishable from cases that do not exist." },
  { title: "Audit trails", text: "Sign-ins, access changes, reviews and exports are recorded with who, what and when, and administrators can review the log." },
  { title: "Privacy-first model use", text: "A local-only mode keeps all processing on your infrastructure. Otherwise only the minimum text needed for a task is sent to the model provider." },
  { title: "Strong authentication", text: "Argon2id password hashing, optional authenticator-app two-factor sign-in, short-lived access tokens and rotating refresh tokens." },
  { title: "Retention controls", text: "Each case carries its own retention period, and administrators can purge cases whose period has ended." },
];

export const STORIES = [
  { org: "A regional patent law firm", metric: "62%", label: "less time collecting references", text: "Associates begin each novelty opinion from a charted shortlist instead of an empty search box." },
  { org: "An industrial equipment manufacturer", metric: "3x", label: "more disclosures screened per quarter", text: "The in-house team ranks incoming disclosures by risk and sends only the strongest to outside counsel." },
  { org: "A university technology transfer office", metric: "4 days", label: "to clear a backlog of 80 disclosures", text: "Two staff members triaged a semester of submissions and gave inventors written reasons for each outcome." },
];

export const FAQ: { q: string; a: string }[] = [
  { q: "Where does the patent data come from?", a: "The index is built from PatentsView granted patent data and the Harvard USPTO Patent Dataset (HUPD) of applications. Both are public datasets, credited in the footer of every page." },
  { q: "How accurate is the analysis?", a: "Search quality is measured on held-out patents, and every claim chart cell shows the passage it relies on. Ratings are decision support for a qualified reviewer, not a legal conclusion." },
  { q: "Is my invention disclosure confidential?", a: "Disclosures are encrypted at rest, visible only to people you grant access, and never used to train models. In local-only mode no text leaves your infrastructure." },
  { q: "Which jurisdictions are covered?", a: "The current index covers United States patents and published applications. Other jurisdictions are not searched, and reports say so." },
  { q: "How are language models used?", a: "Models extract claim elements, rate coverage and draft report text. Every quoted passage is verified against the source, and risk levels come from fixed rules rather than from a model." },
  { q: "What export formats are available?", a: "Reports download as PDF. Analytics tables export as CSV." },
  { q: "How does attorney review work?", a: "A reviewer can comment on and adjust any rating, then sign off the report. Each decision is stored with the reviewer and time, and administrators cannot sign off on a reviewer's behalf." },
  { q: "What are the limitations?", a: "The system searches only its indexed corpus, so it can miss non-patent literature and references outside the United States. It supports a professional search and does not replace one." },
];

export const VALUES = [
  { icon: BookOpenCheck, title: "Evidence over assertion", text: "If we cannot show the passage, we do not make the claim." },
  { icon: ClipboardCheck, title: "People decide", text: "The software prepares the work. Qualified reviewers make the call." },
  { icon: Users, title: "Plain language", text: "Explanations a client can follow, not scores nobody can interpret." },
];

export const TEAM = [
  { name: "Maya Okonkwo", role: "Founder and CEO", bio: "Former patent examiner focused on making prior-art work faster and more transparent." },
  { name: "Daniel Reyes", role: "Head of Engineering", bio: "Builds search and retrieval systems and cares about measurable quality." },
  { name: "Priya Raman", role: "Director of Legal Practice", bio: "Registered patent attorney who shapes how reviews and sign-off work." },
];
