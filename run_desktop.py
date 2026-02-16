from ch_analyser.logging_config import setup_logging
from ch_analyser.desktop.app import App


def main():
    setup_logging()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
