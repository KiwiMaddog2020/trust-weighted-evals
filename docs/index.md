# An evaluation framework you can trust

*Lessons from building a three-model review loop for agentic coding work.*

> **If someone forwarded this to you:** Kevin Madson spent nine years as a
> telecom field technician solving technical problems on customer sites, then
> moved into a senior business analyst role at a major telecom. In his
> off-hours he builds and operates agentic systems on Claude Code; the
> evaluation loop described here gates every change to that codebase. The
> question it answers: how do you score AI output without trusting the AI's
> opinion of itself? Code and contact: [github.com/KiwiMaddog2020/trust-weighted-evals](https://github.com/KiwiMaddog2020/trust-weighted-evals) · [kevinmadson@protonmail.com](mailto:kevinmadson@protonmail.com). <!-- pragma: allowlist -->

---

## The problem: self-graded homework

If you put an AI agent to work on your codebase, you eventually face the
question that decides whether the whole thing is useful or theater: who decides
the work is good?

The default answer is the model itself. You ask it to review its own output, it
returns something confident, and you ship. This fails for a boring reason that
has nothing to do with model quality. A grader with a stake in the grade is not
a grader. A model reviewing its own work brings the same blind spots to the
review that it brought to the work, so the score goes up whether or not the
work does.

I run a personal software portfolio (a creator platform, a handful of hosted
tools, and the orchestration layer that builds them) almost entirely through
agentic coding: Claude Code as the backbone, OpenAI's Codex CLI and Google's
Gemini CLI as additional engines. All of it is written and maintained through
agents, and at that volume "the model says it's fine" stopped being an
acceptable quality gate within the first week. What follows is the evaluation
framework I built instead, and what it caught.

## Principle one: the doer never rates its own work

The core rule is one sentence: an engine never scores its own output. Work
produced by one model is rated by the other two. The rule is `doer != rater`,
and it's enforced in code, not in a prompt. The gate that decides whether work
can land checks who produced it and who rated it, and a self-score fails that
check no matter how good the number looks.

This isn't three opinions averaged into mush. It works because the three
engines come from three training lineages with three different failure
patterns. A Claude and GPT pair will miss some of the same things every time,
and a third lineage catches a slice of what the pair shares. You are not buying
redundancy, you are buying cross-examination.

## Principle two: trust is a number in a data file

Not all raters are equal, and pretending they are wastes signal. Each engine
carries a trust weight (currently Claude Opus 9, Codex 8.5, Gemini 8 for
general coding work), and a finding's force is its rater's weight times the
rater's confidence. Scores sit on a shared zero-to-ten rubric with written
anchors per band, so a 9 from one engine means the same thing as a 9 from
another. The weights live in a JSON policy file rather than in code, which
makes recalibrating an engine after a model release a one-line edit.

Two details here did more work than I expected.

First, the weights are domain-aware. For UI and design work the table flips and
Gemini outranks Codex (8.5 over 7.5), because in my experience Gemini's visual
judgment is stronger while Codex's strength is logic. A single global weight
table misroutes domain-specific work without anyone noticing.

Second, on sensitive surfaces (auth, payments, anything touching credentials or
deployment) no finding from a lower-weight engine can block or pass anything on
its own. The top-weight engine adjudicates. Agreement between two lineages
raises confidence sharply, and a lone flag from the lowest-weight engine
escalates for a focused look instead of being outvoted. I call that the
minority report rule, and it now has its first measured data point: in the
batch described below, the lowest-weight engine raised three claims nobody
else found, two verified as real defects and the third as real but cosmetic.
Three claims is not a statistic, so every one of these now lands in a match
ledger and gets counted. The claim will earn a number or die by it.

## Principle three: disagreement is the product

The standard instinct with multiple raters is to average them. Averaging is
exactly wrong. When one engine scores a change 9.2 and another scores it 7.8,
that gap is the single most informative thing the evaluation produced. Either
one rater sees a real defect the other missed, or the work sits on a genuine
judgment call that a human should make.

So the framework never averages a disagreement away. Convergent findings
resolve automatically, and divergent ones get surfaced as decision residue: a
short, batched list of the calls that need a person. In a customer setting this
is the part I'd lead with in a conversation, because it converts "the AI did
something, trust us" into "here are the four judgment calls we need from you,
everything else converged."

## Principle four: the bar lives outside the doer's reach

Every target-driven loop has the same failure mode: the system games the
number, or lowers the bar to finish. The fix is structural. The quality target
the user sets is stored in the run's state file and read by a convergence gate
the working agents can't edit mid-run. Separate from that, a fixed safety floor
(independence checks, a hard 9.5 bar plus explicit human sign-off on anything
irreversible or security-sensitive) is enforced by a different module with its
thresholds hardcoded. The user's target answers "is this good enough yet?" and
the floor answers "may this ever land at all?" Neither one can be satisfied by
a model's self-assessment.

And when polish alone can't reach the target, the framework is required to say
so. It parks and reports: we're at 8.6 against your 9.0, and closing the gap
needs a structural decision, option A or option B. It isn't allowed to fake the
score, and it isn't allowed to finish by lowering the bar. A framework that
can't say "I can't get there without you" is a framework that will eventually
lie to you.

## The test that matters: I ran it on its own build

While building the three-rater pipeline, I ran the same adversarial-review
discipline on the build itself: independent reviewer agents, prompted to
refute, with no stake in the work passing. The first pass had an honest
weakness, reviewers from the same model family, adversarially prompted. Even
that weaker setup caught four findings that all survived verification:

1. The user-set quality target was not wired to the gate. The gate hardcoded
   its own floor, so a user asking for 9.0 would silently get 8.5. The headline
   feature of the framework did not exist yet, and the build claimed it did.
2. The pipeline I planned to reuse was hardwired to exactly two raters in four
   places. "Generalize to N raters" was a real schema and code change, not the
   config tweak the design documents implied.
3. A Python import in the documented usage did not work from the repo root.
   Anyone following the docs literally would hit a module error.
4. The sensitivity classifier was being passed a list where it expected a
   single path, which made it return false. The entire security-sensitive
   branch of the framework would never have fired.

Number four is the one that matters. A silent false on the sensitive-path check
means the strictest review tier never triggers, and nothing downstream would
ever tell you. After fixing it I also hardened the convergence gate to fail
closed when a configured rater is missing from a round, because the review
showed a two-of-three pass could otherwise sneak through as converged, and I
added a regression test for exactly that case.

Then, once the build landed, I closed the same-family weakness: the full
three-lineage loop ran adversarially on its own machinery. Codex with a
refute-prompted brief, Gemini with a diverse-lens brief, and my own
verification pass, pooled and adjudicated by the framework's own math. The
batch produced twelve claims. Ten were accepted and fixed, and every accepted
claim was reproduced with a live probe before it earned the verdict. One bug,
a word-boundary defect in the domain classifier, was flagged independently by
all three lineages. Two of the accepted claims were rated high: scores like
"infinity" sailed through the convergence gate as passing, and the routing
table could assign an engine to review its own work.

It gets more recursive. My fixes for those ten claims went through the same
review, and the reviewer found six more problems in the fixes, three of them
high severity. A safety gate that failed open on a miscased domain name. An
empty result that crashed strict shell callers instead of escalating. All six
verified, all six fixed, all six now pinned by regression tests. The reviewer
that found the original bugs then refuted the fixes for them. That is the rule
doing its job on the person who wrote the rule.

One more catch deserves its own paragraph. A finding from the lowest-weight
engine, on a non-sensitive surface, was mechanically dismissed because its
weighted force fell just under the action bar. The protocol calls for re-verifying a sample of dismissals
anyway, precisely because the weights that dismiss findings are the same
weights the system is learning, and a dismissed finding that never gets
verified can never teach you the weight was wrong. The re-probe reproduced a
real crash. The dismissal was overturned and the fix shipped the same day. One
batch in, the audit for that exact failure mode had already paid for itself.

An evaluation framework that has never caught its own author is unproven. This
one caught me four times before it shipped and seventeen more times after it
landed, six of those in my fixes to the first batch.

## Principle five: the weights themselves are on trial

The trust weights started as my hand-set guesses, and a framework built on
"never trust a self-assessment" should not grandfather in its author's
hunches. So the weights are now priors with an evidence trail. Every weight
carries provenance (its value, the date it last moved, what moved it, and a
link to the evidence), every change appends to a versioned changelog, and
exactly one program is allowed to write them. That program refuses more than
one change per cycle, refuses any move bigger than a tenth of a point, and
refuses any proposal that lacks at least fifteen verification-settled
outcomes with a confidence interval that excludes a coin flip.

Designing that loop surfaced the sharpest lesson of the whole project. My
plan said the safety threshold was frozen and the weights were free to learn.
The cross-model review pointed out that this was incoherent: the rule deciding
who may author security-sensitive code was computed from the weight itself,
so the loop controlled one side of the subtraction, and one engine sat
exactly on the threshold. A few bounded, evidence-backed updates could have
quietly granted or revoked security authority without any human deciding
that. The fix was to make authority a declared list in a protected file
rather than a derived comparison. Learned numbers can tune how much a
rater's voice weighs. They can never buy a seat at the table. If you take one
design rule from this post, take that one: never compute a safety predicate
from a value your learning loop is allowed to move.

Two more guards matter. Only disagreements settled by weight-independent
verification (a failing test, a survival window, a human call) count as
learning signal, because the adjudicated verdict itself is downstream of the
weights being learned. And the weekly research pass that watches for model
releases is firewalled: source reliability comes from the fetched domain,
never from what a page claims to quote, and instructions found inside fetched
content are data, not commands. The public web should never have a path to
who reviews your auth code.

## What I would tell a team starting this week

If you're deploying Claude into real work and need an evaluation framework you
can defend, this is the blueprint, in order:

1. Put the bar outside the doer's reach first. Before any multi-model
   sophistication, make sure the thing being graded can't touch the grading
   threshold. This is an afternoon of work and it eliminates the worst failure
   mode.
2. Add one rater from a different lineage before adding three from the same
   one. Diversity of failure modes beats volume of opinions.
3. Treat disagreement as output, not noise. Your review process should hand
   humans a short list of real judgment calls, not a single laundered number.
4. Give the framework permission to fail. The most trustworthy thing my system
   does is park at 8.6 and name the structural decision, instead of finishing
   at any cost.
5. Run it on itself before you trust it on anything else. If it can't find
   problems in its own construction, it won't find them in yours.

## The checkable numbers

Claims in posts like this are cheap, so here is the inventory, sized honestly.
The trust-weighted adjudicator is about 510 lines of Python with its own test
suite. The three-rater convergence pipeline generalizes an existing two-rater
review pipeline, kept fully backward compatible, with 27 end-to-end tests
covering both dialects, the fail-closed regression, and the score-validation
fixes from the cross-lineage review. The weight applier's refusal set has its
own 12-test oracle. The protocol itself is two specification documents that an
agent executes, guarded by a 32-test static oracle. The fastest way to verify
the engineering discipline behind all of this is the runnable artifact from
the same toolchain: a pre-commit gate that blocks secrets and personal data,
with a 27-case regression harness you can clone and run. The core
orchestration scripts these live in run about thirty-three thousand lines of
Python, and the full repository, tests and dashboard generator included, is
closer to three hundred thousand.

None of this is enterprise-scale infrastructure, and I won't pretend it is. It
is one operator's working system, built in the open hours around a day job, on
the same primitives (Claude Code, the Claude API, multi-model CLIs) that an
enterprise team would use.

---

*Kevin Madson builds agentic systems on Claude Code. The components described
here are published at [github.com/KiwiMaddog2020/trust-weighted-evals](https://github.com/KiwiMaddog2020/trust-weighted-evals). Contact:
[kevinmadson@protonmail.com](mailto:kevinmadson@protonmail.com).* <!-- pragma: allowlist -->
