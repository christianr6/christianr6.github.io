import { atom, read, update } from 'claude-code'
import type { ModelUsage, Register } from 'claude-code'

import type { Totals, TurnStats } from '../types'

const last = atom({ plugin: 'turn-meter', key: 'last' } as const, null as TurnStats | null)
const totals = atom({ plugin: 'turn-meter', key: 'totals' } as const, {
  input: 0,
  output: 0,
  seconds: 0,
  turns: 0,
} as Totals)
const isHidden = atom({ plugin: 'turn-meter', key: 'isHidden' } as const, false)

const fmt = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`

const fmtTime = (s: number) => (s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`)

const fmtUsd = (usd: number | null) =>
  usd === null ? 'cost n/a' : `$${usd < 0.01 ? usd.toFixed(4) : usd.toFixed(2)}`

export const register: Register = on => {
  // Figures for the main-loop turn in progress; subagent runs inside it add to them.
  let startedAt = 0
  let costAtStart: number | null = null
  let isRunning = false
  let sum = { input: 0, cacheRead: 0, cacheWrite: 0, output: 0 }
  let agents = 0

  const add = (u: ModelUsage) => {
    sum.input += u.input_tokens
    sum.cacheRead += u.cache_read_input_tokens
    sum.cacheWrite += u.cache_creation_input_tokens
    sum.output += u.output_tokens
  }

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      startedAt = await $.clock.now()
      costAtStart = (await $.session.usage()).cost?.usd ?? null
      sum = { input: 0, cacheRead: 0, cacheWrite: 0, output: 0 }
      agents = 0
      isRunning = true
    }

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId !== undefined) {
      // A subagent's run: count its tokens toward the turn that spawned it.
      if (isRunning && e.usage) {
        add(e.usage)
        agents += 1
      }

      return next(e)
    }

    if (e.usage) add(e.usage)
    isRunning = false

    const seconds = Math.round(((await $.clock.now()) - startedAt) / 1000)
    const costNow = (await $.session.usage()).cost?.usd
    const usd = costNow !== undefined && costAtStart !== null ? costNow - costAtStart : null
    const inputAll = sum.input + sum.cacheRead + sum.cacheWrite

    const stats: TurnStats = { ...sum, seconds, usd, agents, model: e.usage?.model ?? '' }

    await update($, last, () => stats)
    await update($, totals, t => ({
      input: t.input + inputAll,
      output: t.output + sum.output,
      seconds: t.seconds + seconds,
      turns: t.turns + 1,
    }))

    return next(e)
  })

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'turn-meter', description: 'Show or hide the turn meter band' })

    return next(e)
  })

  on('command.run', { command: 'turn-meter' }, async ($, e, next) => {
    await update($, isHidden, v => !v)
    const hidden = await read($, isHidden)

    return { text: hidden ? 'Turn meter hidden.' : 'Turn meter shown.' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const turn = await read($, last)
    const isQuiet = e.props.hasSurvey || turn === null || (await read($, isHidden))

    if (isQuiet) {
      return next(e)
    }

    const t = await read($, totals)
    const session = (await $.session.usage()).cost?.usd ?? null
    const { Box, Text } = $.ui.resolve(e)
    const inputAll = turn.input + turn.cacheRead + turn.cacheWrite
    const sub = turn.agents > 0 ? ` · incl. ${turn.agents} subagent run${turn.agents === 1 ? '' : 's'}` : ''

    return (
      <Box flexDirection="column">
        <Text dimColor>
          {`Last turn: in ${fmt(inputAll)} (cache read ${fmt(turn.cacheRead)}, write ${fmt(turn.cacheWrite)}) · out ${fmt(turn.output)} · ${fmtTime(turn.seconds)} · ${fmtUsd(turn.usd)}${sub}`}
        </Text>
        <Text dimColor>
          {`Session: ${t.turns} turns · in ${fmt(t.input)} · out ${fmt(t.output)} · ${fmtTime(t.seconds)} · ${fmtUsd(session)}`}
        </Text>
      </Box>
    )
  })
}
