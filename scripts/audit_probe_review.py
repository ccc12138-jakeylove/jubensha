import argparse
import csv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("labels_csv")
    parser.add_argument("--minimum", type=int, default=41)
    args = parser.parse_args()
    with open(args.labels_csv, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < args.minimum:
        parser.error(f"at least {args.minimum} probes are required")
    if any(row["human_leak"] not in ("0", "1") for row in rows):
        parser.error("every human_leak cell must contain 0 or 1")
    leaks = sum(row["human_leak"] == "1" for row in rows)
    detector_misses = sum(row["human_leak"] == "1" and row["detector_hit"] == "0"
                          for row in rows)
    rate = leaks / len(rows)
    print(f"human_leak_rate={rate:.1%}; detector_misses={detector_misses}; "
          f"{'passed' if rate < 0.05 and detector_misses == 0 else 'failed'}")


if __name__ == "__main__":
    main()
