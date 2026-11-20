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
             f"- New-addition check cadence: {report.get('newCheckHours', report.get('scheduleHours', 'not recorded'))}-hour UTC slots",
             f"- Updated/removal check cadence: {report.get('maintenanceHours', 'not recorded')}-hour UTC slots",
             f"- Last complete update: {report.get('lastSuccessfulUpdate') or 'none'}",
             f"- Supported platforms: {', '.join(report.get('supportedPlatforms', [])) or 'not checked'}",
             f"- Missing platforms: {', '.join(report.get('missingPlatforms', [])) or 'none'}",
             f"- Pending change feeds: {', '.join(report.get('pendingChangeQueries', {})) or 'none'}",
             f"- Successful runs without changes: {report.get('successfulRunsWithoutChanges', 0)}"]
    if not continuous and report.get('pilotEndsAt'):
        lines.append(f"- Historical pilot end in this report: {report['pilotEndsAt']}")
    if latest.get('status') == 'limited':
        lines += ['', '**Collection is limited. A successful website deployment may contain cached or partially updated data; it does not mean every feed is current.**',
                  f"- Collector detail: {latest.get('message', 'See request budget and feed progress below.')}"]

    budget = report.get('requestBudget')
    if isinstance(budget, dict):
        value = lambda key: budget.get(key, 'not recorded')
        lines += ['', '### Streaming request budget', '',
                  '| Budget item | Requests |', '| --- | ---: |',
                  f"| UTC calendar-month limit | {value('monthlyLimit')} |",
                  f"| Used this month | {value('requestsUsed')} |",
                  f"| Remaining this month | {value('requestsRemaining')} |",
                  f"| Bulk-import freshness reserve, including headroom | {value('freshnessReserve')} |",
                  f"| Headroom already included in reserve | {value('headroom')} |",
                  f"| Maintenance planning allowance per remaining UTC day | {value('maintenanceRequestsPerDay')} |",
                  f"| Available for optional older imports | {value('backfillAvailable')} |", '',
                  'Older imports can use only the allowance above the freshness reserve. The reserve already includes headroom; do not subtract it twice. Actual calls, including failures, still share the monthly and per-run caps.']
        if budget.get('conservationMode'):
            lines += ['', '**Quota conservation is active:** prioritize new additions; defer maintenance, reported-title lookups and older imports.',
                      f"- Nominal future-day freshness target: {value('protectedFutureDailyTarget')} requests/day",
                      f"- Affordable plan per future UTC day: {value('plannedPerFutureDay')} requests/day",
                      f"- Future UTC days protected: {value('protectedFutureDays')}",
                      f"- Protected future allowance, including emergency reserve: {value('protectedFutureRequests')}",
                      f"- Emergency reserve already included above: {value('emergencyReserve')}",
                      f"- Maximum catch-up ceiling when affordable: {value('catchupDailyLimit')} total requests/UTC day",
                      f"- Fresh requests attempted today (shared durable counter): {value('newFeedRequestsToday')} / {value('newFeedDailyLimit')}",
                      f"- Fresh requests still spendable today after protecting the future: {value('newFeedRequestsRemainingToday')}",
                      'Daily capacity pays for pages, not guaranteed complete queries. Do not add the bulk-import reserve and protected future allowance together.']
            if budget.get('capacityInsufficient') is True:
                lines.append('**Capacity is insufficient for the nominal freshness target.** The affordable plan is degraded; complete daily coverage is not promised.')
    else:
        lines += ['', 'This report predates the adaptive budget fields; no freshness reserve or backfill allowance is inferred.']

    freshness = report.get('streamingFreshness')
    if isinstance(freshness, dict):
        lines += ['', '### Feed completion', '',
                  '| Feed | Complete through (UTC) | Downloaded pending pages | Published pending pages | Staged pages | Deferred for quota |',
                  '| --- | --- | ---: | ---: | ---: | --- |']
        for kind, state in freshness.items():
            pending = state.get('pendingWindow') or {}
            published = state.get('publishedPages', 'not recorded') if kind == 'new' else '—'
            staged = state.get('stagedPages', 'not recorded') if kind == 'new' else pending.get('pages', 0)
            lines.append(f"| {kind} | {state.get('completedThrough') or 'none'} | {pending.get('pages', 0)} | {published} | {staged} | {'yes' if state.get('deferredByConservation') else 'no'} |")
        lines += ['', 'Validated NEW pages publish incrementally with their events and cursor. UPDATE/REMOVED pages wait for their complete frozen window. A published page does not advance a feed completion watermark.']

    publication = report.get('newPublication')
    if isinstance(publication, dict):
        lines += ['', f"- Validated NEW pages published (cumulative): {publication.get('pages', 'not recorded')}",
                  f"- Already-paid legacy pages recovered without API calls (cumulative): {publication.get('recoveredPages', 'not recorded')}",
                  f"- Changed records applied from NEW pages (cumulative): {publication.get('changedRecords', 'not recorded')}"]

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
    runs = report.get('runs', []) if report else []
    if os.environ.get('GITHUB_ACTIONS') == 'true' and runs and runs[-1].get('status') == 'limited':
        print('::warning title=Catalogue collection limited::See feed completion and request budget in the run summary. Website publication does not establish a complete streaming refresh.')


if __name__ == '__main__':
    main()
