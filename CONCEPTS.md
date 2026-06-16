# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Scanner Pipeline

### Universe
The full set of common stocks across NASDAQ and NYSE (~6,500 tickers) that the Screener starts from each run. Excludes ETFs and test issues.

### Screener
The first pipeline step: downloads one year of OHLC data for the full Universe and applies price, volume, EMA trend, ADR, RSI, and ATH-proximity filters in memory. Only the small passing set proceeds to individual market-cap checks. Outputs a CSV that the scanner steps read.

### Phase 3
The Darvas Box state where a confirmed box is active with no breakout above the ceiling yet. Phase 3 is what the scanner detects as a setup: the stock has completed the ceiling-confirmation and floor-confirmation stages and is coiling inside the box.

### Darvas Box
A price consolidation pattern defined by a ceiling (the high that served as resistance during confirmation) and a floor (the low that held during floor confirmation). The box is confirmed once the ceiling and floor each hold for the required number of contained bars. A close above the ceiling is a breakout and ends the box.

### LC Line
A horizontal resistance line drawn from a pivot high. The line starts as "forming" (too young to trust) and becomes "active" (solid) once it has aged for the minimum number of bars without a close above it. A stock is an LC candidate when the last bar has an active LC Line.

### LW Low
A support-proximity signal, independent of the Darvas Box and LC Line state machines. A stock is an LW Low candidate when its latest close sits within a configurable percentage band (above or below) of the low of the most recently completed Monday–Friday calendar week.

### Ceiling
The resistance high that defines the upper bound of a Darvas Box. Confirmed after the required number of bars close below it. A close above the ceiling triggers a breakout reset.

### Floor
The support low that defines the lower bound of a Darvas Box. Confirmed after the required number of bars hold above it. A wick below the floor without a close below sends the box back to floor-hunting without resetting the ceiling.
