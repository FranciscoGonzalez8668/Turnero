import argparse
from runner import run



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser with UI (headless=False)"
    )
    args = parser.parse_args()

    headless = not args.headed

    run(headless=headless)

if __name__ == "__main__":
    main()
