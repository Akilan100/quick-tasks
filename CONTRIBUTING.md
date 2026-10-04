# Contributing to QuickTasks

Welcome! We love your input! We want to make contributing to QuickTasks as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Development Environment Setup

1. **Fork** the repo on GitHub
2. **Clone** your forked copy to your local machine:
   ```bash
   git clone https://github.com/YOUR_USERNAME/quick-tasks.git
   cd quick-tasks
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Run the App**:
   ```bash
   python src/main.py daemon
   ```

## Running Tests
We use the standard Python `unittest` framework. Before submitting a Pull Request, please ensure all tests pass:
```bash
cd src
python -m unittest discover -s tests -p "test_*.py"
```

## Pull Request Process

1. Create a new branch for your feature or bugfix (`git checkout -b feature/my-new-feature`).
2. Make your modifications.
3. Test your code.
4. Commit your changes (`git commit -am 'Add some feature'`).
5. Push to the branch (`git push origin feature/my-new-feature`).
6. Open a Pull Request against the `main` branch on the original repository.

## Coding Style
- Keep the UI minimal and dark-themed.
- Python code should be clean and readable (we aim to follow PEP 8 standards).
