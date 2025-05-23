# EPUB Translator App

A tool for translating EPUB files.

## Setup Instructions

### 1. Set up your Environment

```bash
python3.12 -m venv venv
```

### 2. Activate the virtual environment

**On macOS/Linux:**
```bash
source venv/bin/activate
```

**On Windows:**
```bash
venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Build the application

```bash
pyinstaller --windowed --name EPUBTranslator compiler.py
```
