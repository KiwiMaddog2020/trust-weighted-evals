---
title: "An evaluation framework you can trust: the doer never rates its own work"
date: 2026-06-12
---

# An evaluation framework you can trust: the doer never rates its own work

<p class="dek">Lessons from building a three-model review loop for agentic coding work.</p>

<p class="meta">Kevin Madson · June 2026 · 8 min read</p>

> **If someone forwarded this to you:** I build and operate agentic systems on
> Claude Code, and the evaluation loop described here gates every change to that
> codebase. The question it answers: how do you score AI output without trusting
> the AI's opinion of itself?

<p class="contact-card">
<a href="https://github.com/KiwiMaddog2020/trust-weighted-evals">github.com/KiwiMaddog2020/trust-weighted-evals</a>
<span class="sep">·</span>
<a href="mailto:kevinmadson@protonmail.com">kevinmadson@protonmail.com</a> <!-- pragma: allowlist -->
</p>

---

## The problem: self-graded homework

Put an AI agent to work on your codebase and you eventually hit the question
that decides whether the whole thing is useful or theater: who decides the work
is good?

The default answer is the model itself. You ask it to review its own output, it
returns something confident, and you ship. This fails for a reason that has
nothing to do with model quality: a grader with a stake in the grade is not a
grader. A model reviewing its own work brings the same blind spots to the review
that it brought to the work, so the score goes up whether or not the work does.

I run a personal software portfolio almost entirely through agentic coding, with
Claude Code as the backbone and OpenAI's Codex and Google's Gemini CLIs as extra
engines. At that volume, "the model says it's fine" stopped being an acceptable
gate within the first week. Here is what I built instead, and what it caught.

## Principle one: the doer never rates its own work

The rule is one sentence: an engine never scores its own output. Work from one
model is rated by the other two. `doer != rater`, enforced in code, not in a
prompt: the gate checks who produced the work and who rated it, and a self-score
fails no matter how good the number looks.

This isn't three opinions averaged into mush. It works because the three engines
come from three training lineages with three different failure patterns. A
Claude and GPT pair miss some of the same things every time; a third lineage
catches a slice of what the pair shares. You are not buying redundancy, you are
buying cross-examination.

## Principle two: trust is a number in a data file

Not all raters are equal, and pretending they are wastes signal. Each engine
carries a trust weight (currently Claude Opus 9, Codex 8.5, Gemini 8 for general
coding), and a finding's force is its rater's weight times its confidence. Scores
sit on a shared zero-to-ten rubric with written anchors, so a 9 from one engine
means what a 9 from another does. The weights live in a JSON file, not in code,
so recalibrating after a model release is a one-line edit.

Two details did more work than I expected. First, the weights are domain-aware:
for UI work the table flips and Gemini outranks Codex, because its visual
judgment is stronger while Codex's strength is logic. A single global table
misroutes domain-specific work without anyone noticing. Second, on sensitive
surfaces (auth, payments, anything touching credentials or deployment) no
lower-weight engine can pass or block on its own. The top-weight engine
adjudicates, agreement between two lineages raises confidence sharply, and a lone
flag from the weakest engine escalates instead of being outvoted. I call that the
minority report rule, and it has its first data point: in the batch below, the
lowest-weight engine raised three claims nobody else found, two real defects and
one real but cosmetic. Three claims is not a statistic, so each now lands in a
match ledger and gets counted.

> The claim will earn a number or die by it.

## Principle three: disagreement is the product

The instinct with multiple raters is to average them. Averaging is exactly
wrong. When one engine scores a change 9.2 and another 7.8, that gap is the most
informative thing the evaluation produced: either one rater sees a defect the
other missed, or the work sits on a genuine judgment call a human should make.

So the framework never averages a disagreement away. Convergent findings resolve
automatically; divergent ones surface as decision residue, a short batched list
of the calls that need a person. In a customer setting this is the part I'd lead
with, because it converts "the AI did something, trust us" into "here are the
four judgment calls we need from you, everything else converged."

## Principle four: the bar lives outside the doer's reach

Every target-driven loop has the same failure mode: the system games the number
or lowers the bar to finish. The fix is structural. The user's quality target
lives in the run's state file, read by a convergence gate the working agents
can't edit mid-run. Separately, a fixed safety floor (independence checks, a hard
9.5 bar, explicit human sign-off on anything irreversible or security-sensitive)
is enforced by a different module with hardcoded thresholds. The target answers
"is this good enough yet?"; the floor answers "may this ever land at all?"
Neither can be satisfied by a self-assessment.

And when polish alone can't reach the target, the framework has to say so. It
parks and reports: we're at 8.6 against your 9.0, and closing the gap needs a
structural decision. It can't fake the score, and it can't finish by lowering the
bar. A framework that can't say "I can't get there without you" will eventually
lie to you.

## The test that matters: I ran it on its own build

While building the three-rater pipeline, I ran the same adversarial review on the
build itself: independent reviewers, prompted to refute, with no stake in the
work passing. The first pass had an honest weakness, the reviewers came from the
same model family, but even that weaker setup caught four findings that all
survived verification:

1. The user's quality target was not wired to the gate. The gate hardcoded its
   own floor, so a request for 9.0 silently got 8.5. The headline feature did not
   exist yet, and the build claimed it did.
2. The pipeline I planned to reuse was hardwired to two raters in four places.
   "Generalize to N raters" was a real schema change, not the config tweak the
   design implied.
3. A documented import did not work from the repo root; anyone following the docs
   would hit a module error.
4. The sensitivity classifier was passed a list where it expected a single path,
   so it returned false. The entire security-sensitive branch would never have
   fired.

Number four is the one that matters: a silent false on the sensitive-path check
means the strictest tier never triggers, and nothing downstream tells you. Fixing
it, I also hardened the gate to fail closed when a configured rater is missing
from a round, and added a regression test for exactly that.

Then I closed the same-family weakness: the full three-lineage loop ran
adversarially on its own machinery. Codex refute-prompted, Gemini with a
diverse-lens brief, my own verification pass, pooled and adjudicated by the
framework's own math. The batch produced twelve claims; ten were accepted and
fixed, each reproduced with a live probe before it earned the verdict. One bug, a
word-boundary defect in the domain classifier, was flagged independently by all
three lineages. Two accepted claims were rated high: scores like "infinity"
sailed through the gate as passing, and the routing table could assign an engine
to review its own work.

It gets recursive. My fixes went through the same review, which found six more
problems in them, three high severity: a safety gate that failed open on a
miscased domain, an empty result that crashed strict shell callers instead of
escalating. All six verified, fixed, and pinned by tests. The reviewer that found
the original bugs then refuted my fixes for them, the rule doing its job on the
person who wrote the rule.

One catch deserves its own note. A finding from the lowest-weight engine, on a
non-sensitive surface, was mechanically dismissed because its weighted force fell
just under the bar. The protocol re-verifies a sample of dismissals anyway,
because the weights that dismiss findings are the same weights the system is
learning, and a dismissal that never gets verified can never teach you the weight
was wrong. The re-probe reproduced a real crash; the dismissal was overturned and
the fix shipped the same day.

| Review pass | Caught | What it found |
| --- | --- | --- |
| Pre-ship, same-family reviewers | 4 | all survived verification; the worst silently disabled the security tier |
| Build batch, three lineages | 10 | accepted and fixed of twelve claims, each reproduced with a live probe |
| Re-review of those fixes | 6 | found in my own fixes, three of them high severity |
| Re-probed dismissal | 1 | overturned a mechanical dismissal; a real crash, shipped the same day |
| **Total against the author** | **21** | four before the build shipped, seventeen after it landed |

## Principle five: the weights themselves are on trial

That batch is why there is a fifth principle.

The weights started as my hand-set guesses, and a framework built on "never trust
a self-assessment" shouldn't grandfather in its author's hunches. So they are now
priors with an evidence trail: every weight carries provenance, every change
appends to a versioned changelog, and exactly one program may write them. That
program refuses more than one change per cycle, any move bigger than a tenth of a
point, and any proposal backed by fewer than fifteen verification-settled
outcomes whose confidence interval excludes a coin flip.

Designing that loop surfaced the sharpest lesson of the project. My plan said the
safety threshold was frozen and the weights were free to learn. The review
pointed out this was incoherent: the rule deciding who may author
security-sensitive code was computed from the weight itself, so the loop
controlled one side of the comparison, and one engine sat exactly on the line. A
few bounded, evidence-backed updates could have quietly granted or revoked
security authority with no human deciding. The fix was to make authority a
declared list in a protected file, not a derived comparison. Learned numbers can
tune how much a rater's voice weighs; they can never buy a seat at the table.

> If you take one design rule from this post, take that one: never compute a
> safety predicate from a value your learning loop is allowed to move.

Two more guards. Only disagreements settled by weight-independent verification (a
failing test, a survival window, a human call) count as learning signal, because
the adjudicated verdict is itself downstream of the weights being learned. And the
weekly pass that watches for model releases is firewalled: source reliability
comes from the fetched domain, never from what a page claims to quote, and
instructions inside fetched content are data, not commands. The public web should
never have a path to who reviews your auth code.

## What I would tell a team starting this week

If you're deploying Claude into real work and need an evaluation framework you can
defend, in order:

1. Put the bar outside the doer's reach first. Before any multi-model
   sophistication, make sure the thing being graded can't touch the grading
   threshold. It's an afternoon of work and it removes the worst failure mode.
2. Add one rater from a different lineage before three from the same one.
   Diversity of failure modes beats volume of opinions.
3. Treat disagreement as output, not noise. Hand humans a short list of real
   judgment calls, not a single laundered number.
4. Give the framework permission to fail. The most trustworthy thing mine does is
   park at 8.6 and name the decision instead of finishing at any cost.
5. Run it on itself before you trust it on anything else. If it can't find
   problems in its own construction, it won't find them in yours.

## The checkable numbers

Claims like these are cheap, so here is the inventory, sized honestly. The
adjudicator is about 510 lines of Python with its own tests. The convergence
pipeline generalizes an existing two-rater pipeline, kept backward compatible,
with 27 end-to-end tests. The weight applier's refusal set has a 12-test oracle.
The protocol is two specification documents an agent executes, guarded by a
30-test oracle. The fastest way to check the discipline behind all of this is the
runnable artifact from the same toolchain: a pre-commit gate that blocks secrets
and personal data, with a [27-case regression harness you can clone and
run](https://github.com/KiwiMaddog2020/trust-weighted-evals). The orchestration
scripts these live in, in the private source, run about thirty-three thousand
lines, and the full repository is closer to three hundred thousand. Clone the
public extract, run the tests, try to refute it.

None of this is enterprise-scale, and I won't pretend it is. It is one operator's
working system, built in the open hours around a day job, on the same primitives
(Claude Code, the Claude API, multi-model CLIs) an enterprise team would use.

---

*I build agentic systems on Claude Code. The components here are published at
[github.com/KiwiMaddog2020/trust-weighted-evals](https://github.com/KiwiMaddog2020/trust-weighted-evals).*
