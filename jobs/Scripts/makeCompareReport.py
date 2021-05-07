import sys
import json
import os
import argparse

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)
        )
    )
import core.performance_counter as perf_count

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work_dir', required=True)
    args = parser.parse_args()
    wd = args.work_dir
    perf_count.event_record(wd, 'Make report json', True)
    reports = [
        json.load(open(os.path.join(wd, e), 'r'))[0] for e in list(
            filter(
                lambda x: x.endswith('RPR.json'), os.listdir(wd)
            )
        )
    ]
    with open(os.path.join(wd, 'report_compare.json'), 'w') as f: json.dump(reports, f, indent=4)
    perf_count.event_record(wd, 'Make report json', False)
