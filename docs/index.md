---
title: "An evaluation framework you can trust: the doer never rates its own work"
date: 2026-06-12
---

# An evaluation framework you can trust: the doer never rates its own work

<p class="dek">When the only thing available to check an AI's work is more AI, how do you get a verdict that means anything? The one rule I enforced in code, and the twenty-one defects it found when I aimed it at itself.</p>

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

You have met the small version of this. You ask a chatbot something, you are not
sure, so you ask it to double-check, and it cheerfully confirms what it just said.
The check felt reassuring and told you nothing. The same mind that made the claim
also reviewed it, carrying the same assumptions into both.

Now scale that up to real work. My agents write and edit code with very little
human typing, which means I cannot read every line, which means a machine has to
judge a machine. That is the question that decides whether the whole approach is
engineering or theater: who gets to declare the work good?

The lazy answer is the model itself. Ask it to review its own output, it returns
something confident, you ship. This fails for a reason that has nothing to do with
how capable the model is. A model brings the identical blind spots to the review
that it brought to the work, so the score climbs whether or not the work earned
it. The correlation between the error and the audit of the error is close to one,
which is another way of saying the audit is worthless. Inside the first week of
building this way, "the model says it's fine" stopped being a gate I believed.
Here is what replaced it.

## Principle one: the doer never rates its own work

One sentence: whichever model produced the work is barred from scoring it. Output
from one model is rated by the other two. That bar lives in the program, not in a
politely worded instruction, so a self-review is discarded before its number is
ever read, however flattering the number.

This is not three opinions averaged into porridge. The three models were built by
three companies on three training pipelines, so their failure modes are
uncorrelated in the ways that matter. Two of them tend to miss an overlapping set
of things; the third catches part of what that pair shares. That is the entire
case for a second opinion from a doctor at a different hospital rather than the
same doctor twice. You are not buying more of the same answer. You are buying an
adversary.

## Principle two: trust is a number in a plain file

Reviewers are not equally reliable, and pretending otherwise discards real
information. So each model carries a trust weight, a scalar for how much its vote
counts. Today, on general coding, Claude sits at 9, OpenAI's model at 8.5,
Google's at 8. A finding's pull on the final score is that reviewer's weight times
its stated confidence, nothing fancier. Every score rides a shared zero-to-ten
scale with a written anchor for each level, so an 8 from one model denotes the
same thing as an 8 from another. The weights live in a flat text file. Re-tuning
trust after a new model ships is a one-line edit, not a code change.

Two details earned their keep. The weights are subject-aware: on visual work the
ranking inverts and Google's model outranks OpenAI's, because it has the better
eye, and a single all-purpose ranking quietly routes the wrong work to the wrong
judge. The second detail is sharper. On anything dangerous, logins, payments,
anything that touches passwords or real users, no lower-ranked model may approve or
veto alone. The top-ranked one has to weigh in, and a lone objection from the
weakest reviewer is escalated to me rather than outvoted and dropped. I call it the
minority report rule, after the premise that the single dissenting voice is
sometimes the correct one. It has already paid off once: further down, the
lowest-ranked model raised three concerns nobody else saw, and two were real
defects.

> The claim will earn a number or die by it.

## Principle three: disagreement is the product

The reflex with multiple reviewers is to average them. That reflex is exactly
backwards. When one model scores a change 9.2 and another 7.8, the 1.4-point gap is
the single most valuable thing the review produced: either one of them caught a
flaw the other slept through, or the change rests on a genuine judgment call that
wants a human. Collapse it to an 8.5 and you have thrown away the signal and
printed a figure that looks precise and carries no information.

So the system never averages a disagreement out of existence. Agreement settles
itself. Real disagreement surfaces as a short list of exactly the calls that need
a person. In a customer setting this is the part I would put first, because it
converts "the AI did some stuff, trust us" into "here are the four decisions we
need from you, and everything else was unanimous."

## Principle four: the bar lives where the worker can't reach it

Any system that optimizes against a target eventually discovers the same exploit:
hit the number by gaming it, or lower the bar and declare victory. Goodhart's law,
in code. The counter has to be structural, not hopeful. The quality target you
set lives in a file the working agents cannot edit at runtime, enforced by a
separate referee they do not control. Next to it sits a fixed safety floor: the
independence checks, a hard minimum score, and a human sign-off on anything
irreversible or security-touching, with thresholds that are simply not writable.
The target asks "is this good enough yet?" The floor asks "is this even allowed to
ship?" Neither question can be answered by a model grading itself.

When polishing cannot close the gap to the target, the system has to say so out
loud. It halts and reports: we are at 8.6 against your goal of 9.0, and the
remaining 0.4 is not more polish, it is a decision only you can make. It cannot
forge the score or finish by sliding the goalposts. A review process that can
never say "I can't get there without you" will lie to you eventually instead.

## The test that matters: I ran it on its own construction

Mid-build, I turned the framework on the framework: independent reviewers,
instructed to tear the work apart, with nothing to gain from a pass. The first
round had an honest weakness, every reviewer came from the same model family, and
it still surfaced four real problems that held up:

1. The quality target you set was never wired to the gate. Ask for a 9.0, get an
   8.5 and no warning. The headline feature did not exist, and the build reported
   that it did.
2. The pipeline I planned to reuse hard-coded exactly two reviewers in four
   places. "Make it work for any number" was a rebuild, not the one-setting change
   the design had assumed.
3. A line in the docs told you to load the tool a way that does not work. Anyone
   following the instructions hit an error on step one.
4. The check that decides whether something is security-sensitive was fed the
   wrong type, so it always returned "no." The entire extra-careful security path
   would never have switched on.

Number four is the dangerous one: a silent "no" there means the strictest tier
never fires and nothing announces that it is asleep. While fixing it, I made the
gate refuse to run if a required reviewer goes missing, and added a test that
fails the moment that bug returns.

Then I closed the weakness and ran the full three-family version on its own
machinery: OpenAI's model told to refute, Google's handed a different angle of
attack, my own pass layered on top. That batch produced twelve concerns. Ten were
real and fixed, each reproduced with a live test before it counted. One bug fired
on all three families at once. Two were serious: a score of literal "infinity"
sailed through the gate, and the routing table could assign a model to review its
own work, the exact thing the system exists to forbid.

It went recursive, which is the part that reassured me most. My fixes ran through
the same review, which found six more problems inside them, three serious. All six
were reproduced, fixed, and pinned with tests. The reviewer that caught the
original bugs then refuted my fixes for them: the rule doing its job on the person
who wrote it. One last catch was almost lost. A finding from the lowest-ranked
model was auto-dismissed for landing just under the bar, but the process
re-samples its own dismissals on purpose, because the weights doing the dismissing
are the same ones it is trying to learn. The re-check reproduced a real crash. The
dismissal was overturned and the fix shipped that day.

| Review pass | Caught | What it found |
| --- | --- | --- |
| Pre-ship, same-family reviewers | 4 | all held up; the worst silently disabled the security tier |
| Build batch, three model families | 10 | real and fixed out of twelve, each reproduced with a live test |
| Re-review of those fixes | 6 | found inside my own fixes, three serious |
| Re-checked dismissal | 1 | overturned an auto-dismissal: a real crash, shipped same day |
| **Total against the author** | **21** | four before it shipped, seventeen after it landed |

## Principle five: the weights themselves are on trial

The trust weights began as my own hand-set guesses, and a system whose first
commandment is "never trust a self-assessment" has no business grandfathering in
its author's hunches. So they are now starting estimates with a paper trail. Each
records where it came from. Every change is logged with a reason. Exactly one
program may edit them, one change at a time, no jump larger than a tenth of a
point, nothing backed by fewer than fifteen settled cases that clear a basic
statistical bar.

Designing that loop surfaced the sharpest lesson of the project. My plan froze the
safety threshold and let the weights learn. The review showed this was quietly
incoherent: the rule deciding which model may even author security-sensitive code
was computed from the weights themselves. The learning loop secretly controlled
one input to its own safety check, and one model sat right on the line. A handful
of small, evidence-backed updates could have silently granted or revoked a model's
security privileges with no human in the loop. The fix was to lift that authority
out of the math entirely: a named list in a protected file, not a number the loop
can nudge. Learned weights may tune how loud a reviewer's voice is. They may never
buy it a seat at the table.

> If you take one design rule from this piece, take that: never let a safety
> decision be computed from a number your learning loop is allowed to change.

## What I would tell a team starting this week

If you are putting Claude, or any capable model, into real work and need a review
process you can defend, in priority order:

1. Put the bar where the worker cannot reach it, first. Before any clever
   multi-model wiring, make sure the thing being graded cannot touch its own
   passing grade. It is an afternoon of work and it removes the worst failure
   mode you have.
2. Add one reviewer from a different model family before you add three from the
   same one. Uncorrelated blind spots beat more of the same opinion.
3. Treat disagreement as the output, not noise. Hand people a short list of real
   decisions, not one averaged number that buries them.
4. Give the system permission to fail. The most trustworthy thing mine does is
   stop at 8.6 and name the decision instead of finishing at any cost.
5. Run it on itself before you trust it on anything else. If it cannot find
   problems in its own construction, it will not find them in yours.

## The checkable numbers

Claims like these are cheap, so here is the honest inventory. The core scoring
program is roughly 510 lines of Python with its own tests. The review pipeline
extends an older two-reviewer version and keeps it working, with 27 end-to-end
tests. The component that moves the weights ships a 12-test set guarding its
refusals. The protocol itself is two written specification documents an agent
follows, guarded by a 30-test set. The easiest piece to check yourself is the
runnable tool from the same toolchain: a guard that fires the instant before code
is saved and blocks secrets and personal data, with a [27-case test suite you can
clone and run](https://github.com/KiwiMaddog2020/trust-weighted-evals). The private
scripts all of this lives in run about thirty-three thousand lines; the full
private repository is closer to three hundred thousand. Clone the public piece,
run the tests, try to prove it wrong.

None of this is enterprise-scale, and I will not pretend it is. It is one
operator's working system, built in the spare hours around a day job, on the same
building blocks an enterprise team would reach for: Claude, the Claude API, and
command-line tools for the other models.

---

<p class="byline"><em>I build agentic systems across multiple coding LLMs. More of my research notes are <a href="/">here</a>.</em></p>