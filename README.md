# MAGI

Three local open-source models convene as a personal decision council and DECIDE.

Named for the Nerv supercomputer in *Neon Genesis Evangelion* — three perspectives, one verdict. Built for indecisive people who want a council, not another chatbot.

```
    ███╗   ███╗ █████╗  ██████╗ ██╗
    ████╗ ████║██╔══██╗██╔════╝ ██║
    ██╔████╔██║███████║██║  ███╗██║
    ██║╚██╔╝██║██╔══██║██║   ██║██║
    ██║ ╚═╝ ██║██║  ██║╚██████╔╝██║
    ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝

    MELCHIOR  ·  BALTHASAR  ·  CASPER
    the council convenes — bring your question
```

## What it does

You bring a question. Three models, each running a distinct lens, debate it across multiple rounds and return a verdict:

- **MELCHIOR** (`qwen2.5:7b`) — data, logic, second-order effects. Watches for confirmation bias, sunk cost, planning fallacy.
- **BALTHASAR** (`qwen3:4b`) — long-term wellbeing, relationships, what gets sacrificed quietly. Asks who gets hurt if it fails, what's irreversible.
- **CASPER** (`mistral:latest`) — desire, values, identity. Sees through performance, asks what you'd regret NOT doing.

The council always decides. CONDITIONAL verdicts require a concrete blocker — vague hedges are coerced to ACCEPT. If the three disagree, you get DEADLOCK and the call goes back to you, but with three distinct readings to argue with.

## Install

```bash
pipx install git+https://github.com/0arch-io/magi
```

Requires [Ollama](https://ollama.com) running locally with the default models pulled:

```bash
ollama pull qwen2.5:7b
ollama pull qwen3:4b
ollama pull mistral
```

Total footprint ≈ 11GB.

## Use

```bash
magi                                    # open the REPL
magi "should I take the job offer?"     # one-shot
magi --invite banker --invite therapist "should I move cities?"
```

Inside the REPL:

```
❯  bring a question
❯❯ argue back — the council reconsiders with new info
/new       drop the thread, start fresh
/help      list commands
```

## How it routes your question

A lightweight intake classifier routes each question into one of three flows:

### `decision` — yes/no
```
❯ should i deprecate the v1 api now that v2 has 90% of traffic
intake: decision question
... [3 rounds of debate]
RESULT: CONSENSUS — YES  (3A · 0C · 0R)
```

### `choice` — pick from named options
```
❯ should i write my new ios app in swift or react native
intake: choice question — Swift vs React Native
... [picks per persona, tally]
RESULT: CONSENSUS — Swift  (Swift:3)
```

### `open` — open-ended request for direction
```
❯ what should i build for my next side project
intake: open question
MELCHIOR    RECOMMENDS: a data visualization tool for personal finance
BALTHASAR   RECOMMENDS: a small-scale community garden in your neighborhood
CASPER      RECOMMENDS: a personal growth journal with guided questions
RESULT: 3 DISTINCT PICKS — your call: pick the lens that speaks to you
```

`prediction` questions ("will my startup hit profitability?") are interpreted as decisions — *should they bet on X happening.*

## Specialists

The core MAGI is fixed at three. For higher-stakes questions, invite a specialist:

```
/invite banker      financial reality — cash flow, runway, opportunity cost
/invite therapist   emotional + psychological — what's underneath
/invite lawyer      legal exposure — contracts, liability, downside
/invite coach       career trajectory — what compounds, what's a dead-end
/invite doctor      physical health — body signals, lifestyle impact
```

Specialists join the council and debate alongside the core three. `/dismiss <name>` to remove. They can be invited mid-thread.

## Journal

Every deliberation auto-saves to `~/.config/magi/journal.jsonl`:

```
/journal                       show recent deliberations
/outcome <id> <what you did>   record what you actually decided
```

Useful for spotting patterns ("you DEADLOCKED 8 times this month, mostly on relationship questions").

## Customize

Per-persona model overrides:

```bash
magi --melchior qwen3:8b --balthasar hermes3:8b "..."
```

Or in the REPL:

```
/melchior qwen3:8b
/balthasar llama3.1:8b
```

Override the intake classifier model:

```bash
MAGI_CLASSIFIER_MODEL=llama3.2:1b magi
```

Point at a non-local Ollama:

```bash
OLLAMA_HOST=http://192.168.1.100:11434 magi
```

## Caveats

- **Math is hallucinated.** Small models confidently get arithmetic wrong. For prediction questions involving numbers (runway, breakeven, growth rates), trust the directional verdict, not the specific figures.
- **The council DECIDES.** It will not refuse to vote, even on questions where it lacks information. That's a feature — refusing to decide is the worst outcome — but the corollary is that vague questions get vague-but-decisive answers.
- **Three is canon.** Don't try to add a fourth core member. Route through specialists instead.

## Why

Coin-flip 2.0. The value is the experience: three independent reads, watching them debate each other by name, surfacing your real preference by friction. It scales from "should I have coffee at 8pm" to "should I quit my job" — invite specialists for the heavy ones.

Built explicitly for people who can't decide on their own. The council won't let you wallow.

## License

MIT. See `LICENSE`.
