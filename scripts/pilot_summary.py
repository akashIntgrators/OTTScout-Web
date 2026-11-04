"""Append a secret-free continuous-collector summary to the GitHub Actions run."""
import json
import os
from pathlib import Path


def build_summary(report):
    if report is None:
        return '## OTTScout catalogue collector\n\nNo report produced. Check the missing secret or database message above.\n'

    runs = report.get('runs', [])
    latest = runs[-1] if runs else {}
    continuous = report.get('collectorMode') == 'continuous'
    lines = ['## OTTScout catalogue collector', '',
             f"- Latest status: {latest.get('status', 'not started')}",
             '- Collection: ongoing; no scheduled end' if continuous else '- Collector mode: legacy report; continuous mode not recorded',
             f"- Original initialization: {report.get('pilotStartedAt', 'not recorded')}",
             f"- Requests this run: {latest.get('requests', 0)}",
             f"- Requests this UTC month: {report.get('requestsThisMonth', 'not recorded')}",
             f"- Requests since original initialization: {report.get('requestsDuringPilot', 'not recorded')}",
             f"- New-addition check cadence: {report.get('scheduleHours', 'not recorded')}-hour UTC slots",
             f"- Updated/removal check cadence: {report.get('maintenanceHours', 'not recorded')}-hour UTC slots",
             f"- Last complete update: {report.get('lastSuccessfulUpdate') or 'none'}",
             f"- Supported platforms: {', '.join(report.get('supportedPlatforms', [])) or 'not checked'}",
             f"- Missing platforms: {', '.join(report.get('missingPlatforms', [])) or 'none'}",
             f"- Pending change feeds: {', '.join(report.get('pendingChangeQueries', {})) or 'none'}",
             f"- Successful runs without changes: {report.get('successfulRunsWithoutChanges', 0)}"]
    if not continuous and report.get('pilotEndsAt'):
        lines.append(f"- Historical pilot end in this report: {report['pilotEndsAt']}")

    budget = report.get('requestBudget')
    if isinstance(budget, dict):
        value = lambda key: budget.get(key, 'not recorded')
        lines += ['', '### Streaming request budget', '',
                  '| Budget item | Requests |', '| --- | ---: |',
                  f"| UTC calendar-month limit | {value('monthlyLimit')} |",
                  f"| Used this month | {value('requestsUsed')} |",
                  f"| Remaining this month | {value('requestsRemaining')} |",
                  f"| Protected freshness reserve, including headroom | {value('freshnessReserve')} |",
                  f"| Headroom already included in reserve | {value('headroom')} |",
                  f"| Maintenance planning allowance per remaining UTC day | {value('maintenanceRequestsPerDay')} |",
                  f"| Available for optional older imports | {value('backfillAvailable')} |", '',
                  'Older imports can use only the allowance above the freshness reserve. The reserve already includes headroom; do not subtract it twice. Actual calls, including failures, still share the monthly and per-run caps.']
    else:
        lines += ['', 'This report predates the adaptive budget fields; no freshness reserve or backfill allowance is inferred.']

    lines += ['', report.get('catalogScope', 'Imported coverage is partial.'), '',
              'Review the report artifact for run history. Scheduled times are approximate. Daily maintenance means the last complete watermark can be older than the latest new-addition check.']

    catalog = report.get('catalog')
    if isinstance(catalog, dict):
        lines += ['', '### Imported catalogue coverage', '',
                  f"{catalog['totalTitles']} unique titles stored; {catalog['titlesWithTargetAudio']} have reported target audio; valid offers with missing audio remain visible without a specific language filter.", '',
                  '| Platform | Offers | Offers with target audio | Audio unverified |',
                  '| --- | ---: | ---: | ---: |']
        for name, stats in catalog.get('platforms', {}).items():
            lines.append(f"| {name} | {stats['offers']} | {stats['offersWithTargetAudio']} | {stats['unknownAudioOffers']} |")
        lines += ['', 'Counts describe imported titles, not complete platform coverage.', '', '### Data quality', '',
                  f"- Titles with unverified offer audio: {catalog.get('titlesWithUnknownAudio', 0)}",
                  f"- Titles without current offers: {catalog.get('titlesWithoutOffers', 0)}",
                  f"- Titles not checked for over seven days: {catalog.get('titlesNotCheckedFor7Days', 0)}"]
        for item in report.get('titleRechecks', []):
            lines.append(f"- Reported title recheck: {item.get('title', 'Unknown')} — {'resolved' if item.get('resolved') else item.get('status', 'pending provider match')}")

    backfill = report.get('catalogBackfill', {}).get('platforms')
    if backfill:
        lines += ['', '### Older catalogue import progress', '', '| Platform | Movie pages | Series pages |', '| --- | ---: | ---: |']
        for name, pages in backfill.items():
            lines.append(f"| {name} | {pages['movie']} | {pages['series']} |")
        lines += ['', 'Pages are imported in rotation when budget permits. These counts do not mean a complete platform catalogue.']
    return '\n'.join(lines) + '\n'


def main():
    path = Path('reports/pilot.json')
    report = json.loads(path.read_text()) if path.exists() else None
    text = build_summary(report)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as handle:
            handle.write(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
