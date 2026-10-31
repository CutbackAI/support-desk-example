import argparse


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the independent local support-desk example.")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    uvicorn.run(
        "example_supportdesk.web:app",
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
