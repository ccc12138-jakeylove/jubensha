import argparse
import csv

from jubensha.eval.metrics import cohen_kappa


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("labels_csv", help="CSV with human,model integer label columns")
    args = parser.parse_args()
    with open(args.labels_csv, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < 20:
        parser.error("at least 20 paired labels are required")
    value = cohen_kappa([int(row["human"]) for row in rows],
                        [int(row["model"]) for row in rows])
    print(f"kappa={value:.3f}; {'passed' if value >= 0.6 else 'rubric revision required'}")


if __name__ == "__main__":
    main()
