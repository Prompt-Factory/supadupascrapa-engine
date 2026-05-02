import argparse

from handler import handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run V3.1 scrape for configured regions.",
    )
    parser.add_argument(
        "--region-code",
        help="Run only one region code, e.g. KR",
    )
    parser.add_argument(
        "--max-pages-per-scope",
        type=int,
        help="Limit page count per scope for testing.",
    )
    parser.add_argument(
        "--log-every-pages",
        type=int,
        help="Print page-level progress every N pages.",
    )
    parser.add_argument(
        "--chart-only",
        action="store_true",
        help="Run only the mostPopular chart lane.",
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="Run only the broad search lane.",
    )
    parser.add_argument(
        "--search-lookback-days",
        type=int,
        default=7,
        help="Broad search publishedAfter lookback window in days.",
    )
    parser.add_argument(
        "--skip-save",
        action="store_true",
        help="Do not write output files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.chart_only and args.search_only:
        raise SystemExit("Choose only one of --chart-only or --search-only")

    include_chart_lane = not args.search_only
    include_search_lane = not args.chart_only

    event = {
        "logProgress": True,
        "printResponse": False,
        "includeOverallChart": include_chart_lane,
        "includeCategoryCharts": include_chart_lane,
        "includeSearchLane": include_search_lane,
        "searchLookbackDays": args.search_lookback_days,
        "saveToFile": not args.skip_save,
        "saveSplitFiles": not args.skip_save,
        "saveBundleFile": not args.skip_save,
    }

    if args.region_code:
        event["regionCode"] = args.region_code.upper()
    else:
        event["runAllRegions"] = True

    if args.max_pages_per_scope:
        event["maxPagesPerScope"] = args.max_pages_per_scope
    if args.log_every_pages:
        event["logEveryPages"] = args.log_every_pages

    handler(event, None)


if __name__ == "__main__":
    main()
