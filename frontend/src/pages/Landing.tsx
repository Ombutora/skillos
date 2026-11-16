import { Link } from "react-router-dom";
import { Logo } from "../components/Logo";

const STAGES = [
  { k: "01", t: "Capture", d: "An expert records a demonstration on a phone. SkillOS samples the keyframes, transcribes the narration and segments the actions." },
  { k: "02", t: "Compile", d: "The demonstration becomes a skill graph: steps, tools, dependencies, branches, safety rules and checks, each linked to the moment in the video it came from." },
  { k: "03", t: "Guide", d: "Learners follow the approved procedure while the camera and their multimeter readings are checked against each step." },
  { k: "04", t: "Verify", d: "Every score comes from recorded evidence. If SkillOS can't see something, it says so." },
];

export default function Landing() {
  return (
    <div className="min-h-full bg-ink-900 text-white">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <Logo dark />
        <div className="flex gap-2 text-sm">
          <Link to="/login" className="rounded-lg px-3 py-2 text-ink-300 hover:text-white">Sign in</Link>
          <Link to="/register" className="rounded-lg bg-accent px-3 py-2 font-medium hover:bg-accent-strong">Get started</Link>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-20 pt-12 sm:px-6 lg:grid-cols-2 lg:pt-20">
        <div>
          <p className="text-sm font-medium text-accent">Practical skills intelligence</p>
          <h1 className="mt-4 text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">Human expertise, converted into executable intelligence.</h1>
          <p className="mt-5 max-w-lg text-lg text-ink-300">Capture how experts work. Turn their knowledge into interactive practical training. Verify what people can actually do.</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/login" className="rounded-lg bg-accent px-5 py-3 font-medium hover:bg-accent-strong">Try the solar demo</Link>
            <a href="#how" className="rounded-lg border border-ink-600 px-5 py-3 font-medium text-ink-300 hover:text-white">How it works</a>
          </div>
        </div>
        <DemoPanel />
      </section>

      <section id="how" className="bg-ink-950 py-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <h2 className="text-2xl font-semibold">From demonstration to verified competency</h2>
          <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-ink-700 sm:grid-cols-2 lg:grid-cols-4">
            {STAGES.map((s) => (
              <div key={s.k} className="bg-ink-900 p-6">
                <p className="font-mono text-sm text-accent">{s.k}</p>
                <h3 className="mt-3 font-semibold">{s.t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-300">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <h2 className="text-2xl font-semibold">Built for training where mistakes have consequences</h2>
        <div className="mt-8 flex flex-wrap gap-2">
          {["TVET institutions", "Solar installers", "Technical colleges", "Equipment maintenance", "Manufacturing", "Automotive repair", "Industrial safety"].map((x) => (
            <span key={x} className="rounded-full border border-ink-600 px-4 py-2 text-sm text-ink-300">{x}</span>
          ))}
        </div>
        <div className="mt-14 rounded-2xl bg-ink-800 p-8 sm:flex sm:items-center sm:justify-between">
          <div>
            <h3 className="text-xl font-semibold">Start with 12 V solar lighting</h3>
            <p className="mt-1 text-ink-300">Three modules: installation, troubleshooting and component identification.</p>
          </div>
          <Link to="/register" className="mt-5 inline-block rounded-lg bg-accent px-5 py-3 font-medium hover:bg-accent-strong sm:mt-0">Create an organization</Link>
        </div>
      </section>
      <footer className="border-t border-ink-700 py-6 text-center text-xs text-ink-400">SkillOS training content is limited to isolated low-voltage DC systems.</footer>
    </div>
  );
}

/** Illustrative mock of the validation panel (labelled as such). */
function DemoPanel() {
  const rows = [
    { t: "Check battery voltage", v: "VERIFIED", c: "text-verified", m: "12.7 V within 11.8–13.6 V" },
    { t: "Isolate the system", v: "VERIFIED", c: "text-verified", m: "Panel covered · fuse removed" },
    { t: "Connect battery to controller", v: "FAILED", c: "text-failed", m: "−12.6 V: polarity reversed. Remove fuse and swap cables." },
    { t: "Connect battery to controller", v: "UNCERTAIN", c: "text-uncertain", m: "BAT− terminal not visible. Move camera closer." },
  ];
  return (
    <div className="rounded-2xl border border-ink-700 bg-ink-800 p-5 shadow-2xl" aria-label="Example of SkillOS validation feedback">
      <div className="flex items-center justify-between text-xs text-ink-400"><span>Example session feedback</span><span className="font-mono">illustration</span></div>
      <ul className="mt-4 space-y-3">
        {rows.map((r, i) => (
          <li key={i} className="rounded-xl bg-ink-900 p-4">
            <div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">{r.t}</span><span className={`text-xs font-semibold ${r.c}`}>{r.v}</span></div>
            <p className="mt-1 text-sm text-ink-300">{r.m}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
