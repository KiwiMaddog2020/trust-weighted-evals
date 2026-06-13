---
title: "An evaluation framework you can trust: the doer never rates its own work"
date: 2026-06-12
---

# An evaluation framework you can trust: the doer never rates its own work

<p class="dek">When the only thing on hand to check an AI's work is more AI, how do you get a verdict you can trust? The rule I settled on, and the twenty-one problems it found when I pointed it at itself.</p>

<p class="meta">Kevin Madson · June 2026 · 8 min read</p>

> **If someone forwarded this to you:** I build software with AI agents, programs
> that write and change code on their own, across several different AI models. The
> review process below is the gate every change has to pass. The question it
> answers: how do you score an AI's work without simply trusting the AI's opinion
> of itself?

<p class="contact-card">
<a href="https://github.com/KiwiMaddog2020/trust-weighted-evals">github.com/KiwiMaddog2020/trust-weighted-evals</a>
<span class="sep">·</span>
<a href="mailto:kevinmadson@protonmail.com">kevinmadson@protonmail.com</a> <!-- pragma: allowlist -->
</p>

---

## The problem: self-graded homework

You have probably met this problem in miniature. You ask a chatbot something,
you are unsure, so you ask it to double-check, and it cheerfully confirms what it
just said. The check felt reassuring and told you nothing: the same mind that made
the claim also reviewed it.

Now run that at the scale of real work. I build software with AI agents, programs
that write and edit code on their own with very little human typing, so I cannot
read every line myself. That forces the question that decides whether the whole
approach is useful or just theater: who decides the work is good?

The tempting answer is the model itself. You ask it to review its own output, it
returns something confident, and you ship. This fails for a reason that has
nothing to do with how smart the model is. It is the same reason a student does
not grade their own exam: the model brings the very same blind spots to the review
that it brought to the work, so the score goes up whether or not the work deserves
it. Within my first week of building this way, "the model says it's fine" stopped
being a gate I could believe. Here is what replaced it, and what it caught.

## Principle one: the doer never rates its own work

The core rule is one sentence: whichever AI did the work is never allowed to score
it. Work from one model is rated by the other two. I enforce that in the program
itself, not by politely asking in the instructions, so a self-review is thrown out
no matter how good its number looks.

This is not three opinions blended into mush. The three AIs were built by three
companies and trained three different ways, so they fail in three different ways.
Two of them miss some of the same things every time; the third catches a slice of
what that pair shares. It is why you get a second opinion from a doctor at a
different hospital, not the same one twice. You are not buying more of the same
answer. You are buying cross-examination.

## Principle two: trust is a number in a plain file

Not all reviewers are equally good, and pretending they are throws away
information. So each AI carries a trust weight, a number for how much its vote
counts (today, on general coding, Claude is a 9, OpenAI's model an 8.5, Google's
an 8). How far a finding moves the needle is just that reviewer's weight times how
confident it was. Every score sits on a shared zero-to-ten scale with written
descriptions for each level, so an 8 from one AI means what an 8 from another
does. The weights live in a plain text file, so re-tuning trust after a new model
ships is a one-line change.

Two details did more work than I expected. First, the weights know the subject:
for visual work the order flips and Google's model outranks OpenAI's, because it
has the better eye. A single all-purpose ranking quietly sends the wrong work to
the wrong judge. Second, on anything dangerous (logins, payments, anything
touching passwords or real users) no lower-ranked AI can approve or veto alone.
The top-ranked one must weigh in, and a lone worry from the weakest one gets
escalated to me rather than outvoted and forgotten. I call that the minority
report rule, after the idea that the one dissenting voice might be the right one.
It has its first case already: below, the lowest-ranked AI raised three concerns
nobody else saw, and two were genuine defects.

> The claim will earn a number or die by it.

## Principle three: disagreement is the product

The instinct with several reviewers is to average them. That is exactly wrong.
When one AI rates a change 9.2 and another 7.8, that gap is the most useful thing
the review produced: either someone caught a flaw the other missed, or the work
sits on a real judgment call a human should make. Averaging it into an 8.5 throws
the signal away and prints a number that feels precise and means nothing.

So the system never averages a disagreement away. Agreement resolves on its own;
genuine disagreement surfaces as a short list of exactly the calls that need a
person. In a customer setting this is the part I would lead with, because it turns
"the AI did some stuff, trust us" into "here are the four decisions we need from
you, and everything else was unanimous."

## Principle four: the bar lives where the worker can't reach it

Every system that chases a target eventually learns the same trick: hit the number
by gaming it, or quietly lower the bar so it can declare victory. The fix has to
be structural. The quality target you set lives in a file the working agents
cannot edit while they run, checked by a separate referee they do not control.
Beside it sits a fixed safety floor (the independence checks, a hard minimum
score, and a human sign-off on anything irreversible or security-related) with
thresholds that are simply not adjustable. The target asks "is this good enough
yet?" The floor asks "is this even allowed to ship?" Neither can be answered by an
AI grading itself.

And when polishing cannot reach the target, the system has to say so. It stops and
reports: we are at 8.6 against your goal of 9.0, and closing that gap is not more
polish, it is a decision you need to make. It cannot fake the score or finish by
moving the goalposts. A review process that can never say "I can't get there
without you" will eventually lie to you instead.

## The test that matters: I ran it on its own construction

While building this, I turned it on the thing I was building: independent
reviewers, told to tear the work apart, with nothing to gain from it passing. The
first round had an honest weakness (the reviewers all came from the same family of
model), yet it still found four real problems that held up:

1. The quality target you set was never wired to the gate. Asking for a 9.0
   silently got you an 8.5. The headline feature did not exist, and the build
   claimed it did.
2. The pipeline I meant to reuse was hard-wired to exactly two reviewers in four
   places. "Make it work for any number" was a real rebuild, not the small setting
   change the design assumed.
3. A line of the docs told you to load the tool a way that did not work. Anyone
   following the instructions hit an error on step one.
4. The check that decides whether something is security-sensitive was handed the
   wrong kind of input, so it always answered "no." The entire extra-careful
   security path would never have switched on.

Number four is the one that matters: a silent "no" there means the strictest tier
never fires and nothing tells you it is asleep. Fixing it, I also made the gate
refuse to run if a required reviewer goes missing, and added a test that fails if
the bug ever returns.

Then I closed the weakness and ran the full three-family version on its own
machinery: OpenAI's model told to refute, Google's given a different angle to
attack from, my own pass on top. That batch produced twelve concerns; ten were
real and fixed, each reproduced with a live test before it counted. One bug was
flagged by all three families at once. Two were serious: a score of literal
"infinity" passed the gate, and the routing table could assign an AI to review its
own work, the one thing the system exists to forbid.

It gets recursive, which reassured me. My fixes went through the same review,
which found six more problems inside them, three serious. All six were verified,
fixed, and locked in with tests. The reviewer that found the original bugs then
refuted my fixes for them: the rule doing its job on the person who wrote it. One
last catch: a finding from the lowest-ranked AI was auto-dismissed for falling
just under the bar, but the process re-checks a sample of dismissals on purpose,
because the weights doing the dismissing are the same ones it is trying to learn.
The re-check reproduced a real crash. The dismissal was overturned and the fix
shipped that day.

| Review pass | Caught | What it found |
| --- | --- | --- |
| Pre-ship, same-family reviewers | 4 | all held up; the worst silently disabled the security tier |
| Build batch, three model families | 10 | real and fixed out of twelve, each reproduced with a live test |
| Re-review of those fixes | 6 | found inside my own fixes, three serious |
| Re-checked dismissal | 1 | overturned an auto-dismissal: a real crash, shipped same day |
| **Total against the author** | **21** | four before it shipped, seventeen after it landed |

## Principle five: the weights themselves are on trial

The trust weights started as my own hand-set guesses, and a system built on "never
trust a self-assessment" should not grandfather in its author's hunches. So they
are now starting estimates with a paper trail: each records where it came from,
every change is logged with a reason, and exactly one program may change them, no
more than one change at a time, no jump bigger than a tenth of a point, nothing
backed by fewer than fifteen settled cases that clear a basic statistical bar.

Designing that loop surfaced the sharpest lesson of the project. My plan froze the
safety threshold and let the weights learn. The review showed this was quietly
incoherent: the rule deciding which AI may even author security-sensitive code was
calculated from the weights themselves, so the learning loop secretly controlled
one side of its own safety check, and one model sat right on the line. A few small,
evidence-backed updates could have silently granted or stripped an AI's security
privileges with no human involved. The fix was to make that authority a named list
in a protected file, not a number the loop can move. Learned numbers may tune how
loud a reviewer's voice is. They may never buy it a seat at the table.

> If you take one design rule from this piece, take that one: never let a safety
> decision be calculated from a number your learning loop is allowed to change.

## What I would tell a team starting this week

If you are putting Claude (or any capable model) into real work and need a review
process you can defend, in order:

1. Put the bar where the worker cannot reach it, first. Before any clever
   multi-model setup, make sure the thing being graded cannot touch its own
   passing grade. It is an afternoon of work and removes the worst failure mode.
2. Add one reviewer from a different model family before three from the same one.
   Different blind spots beat more of the same opinion.
3. Treat disagreement as the output, not noise. Hand people a short list of real
   decisions, not one averaged number that hides them.
4. Give the system permission to fail. The most trustworthy thing mine does is
   stop at 8.6 and name the decision instead of finishing at any cost.
5. Run it on itself before you trust it on anything else. If it cannot find
   problems in its own construction, it will not find them in yours.

## The checkable numbers

Claims like these are cheap, so here is the honest inventory. The core scoring
program is about 510 lines of Python with its own tests. The review pipeline
extends an older two-reviewer version and keeps it working, with 27 end-to-end
tests. The piece that changes the weights has a 12-test set guarding its refusals.
The protocol is two written specification documents an agent follows, guarded by a
30-test set. The easiest part to check yourself is the runnable tool from the same
toolchain: a guard that runs the moment before code is saved and blocks secrets and
personal data, with a [27-case test suite you can clone and
run](https://github.com/KiwiMaddog2020/trust-weighted-evals). The private scripts
all of this lives in run about thirty-three thousand lines, and the full private
repository is closer to three hundred thousand. Clone the public piece, run the
tests, try to prove it wrong.

None of this is enterprise-scale, and I will not pretend it is. It is one
operator's working system, built in the spare hours around a day job, on the same
building blocks (Claude, the Claude API, and command-line tools for the other
models) an enterprise team would reach for.

---

<p class="byline"><em>I build agentic systems across multiple coding LLMs. More of my research notes are <a href="/">here</a>.</em></p>
