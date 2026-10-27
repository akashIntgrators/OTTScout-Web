"""Append a secret-free pilot status summary to the GitHub Actions run."""
import json
import os
from pathlib import Path

path = Path('reports/pilot.json')
if path.exists():
    report = json.loads(path.read_text())
    latest = report['runs'][-1] if report['runs'] else {}
    lines = ['## OTTScout 30-day pilot', '',
             f"- Latest status: {latest.get('status', 'not started')}",
             f"- Requests this run: {latest.get('requests', 0)}",
             f"- Requests this month: {report['requestsThisMonth']}",
             f"- Requests during pilot: {report['requestsDuringPilot']}",
             f"- Last complete update: {report['lastSuccessfulUpdate'] or 'none'}",
             f"- Supported platforms: {', '.join(report['supportedPlatforms']) or 'not checked'}",
             f"- Missing platforms: {', '.join(report['missingPlatforms']) or 'none'}",
             f"- Pilot stops: {report['pilotEndsAt']}",
             f"- Successful runs without changes: {report['successfulRunsWithoutChanges']}",
             '', report['catalogScope'], '',
             'Review the report artifact for run history. Scheduled times are approximate.']
else:
    lines = ['## OTTScout pilot', '', 'No report produced. Check the missing secret or database message above.']
if path.exists() and 'catalog' in report:
    catalog = report['catalog']
    lines += ['', '### Imported sample coverage', '',
              f"{catalog['totalTitles']} unique titles stored; {catalog['titlesWithTargetAudio']} have verified target audio and can appear in the dashboard.", '',
              '| Platform | Offers | Offers with target audio | Audio unverified |',
              '| --- | ---: | ---: | ---: |']
    for name, stats in catalog['platforms'].items():
        lines.append(f"| {name} | {stats['offers']} | {stats['offersWithTargetAudio']} | {stats['unknownAudioOffers']} |")
    lines += ['', 'Counts describe the imported sample, not complete platform coverage.']
if path.exists() and report.get('catalogBackfill', {}).get('platforms'):
    lines += ['', '### Older catalogue import progress', '', '| Platform | Movie pages | Series pages |', '| --- | ---: | ---: |']
    for name, pages in report['catalogBackfill']['platforms'].items():
        lines.append(f"| {name} | {pages['movie']} | {pages['series']} |")
    lines += ['', 'Pages are imported in rotation. These counts do not mean a complete platform catalogue.']
text = '\n'.join(lines) + '\n'
summary = os.environ.get('GITHUB_STEP_SUMMARY')
if summary:
    with open(summary, 'a') as handle:
        handle.write(text)
else:
    print(text)

