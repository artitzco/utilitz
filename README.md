# utilitz

**utilitz** is a versatile Python utility library designed to simplify common tasks such as data persistence, Excel table manipulation, system automation, and advanced pattern matching.

It is built with a modular approach, keeping the core library lightweight while providing powerful specialized modules through optional dependencies.

Current release: **0.9.0**

## 🚀 Installation

### Core (Lightweight)
Installs only the essential utilities for text, JSON, and object serialization.
```bash
pip install utilitz
```

### With Specialized Modules
Install specific modules as needed to keep your environment lean:
```bash
# For Excel and Dataframe support
pip install utilitz[office]

# For GUI automation and Activity monitoring
pip install utilitz[gui]

# For Encryption and Decryption
pip install utilitz[crypto]

# Install everything
pip install utilitz[all]
```

## ✨ Key Features

### 📁 Core IO Utilities
Simple functions for saving and loading data without boilerplates.
- `save_text` / `load_text`: Handle lists of strings.
- `save_json` / `load_json`: Work with dictionary and list structures.
- `save_object` / `load_object`: Convenient pickle serialization.

### 📊 Excel & Data (Optional: `[office]`)
- `read_excel_table`: Intelligently reads tables from Excel files, with support for row filtering based on regex patterns and dynamic range detection.
- `encode_column` / `decode_column`: Convert between Excel column names (e.g., "A", "AB") and numeric indices.

### 🛡️ Crypto (Optional: `[crypto]`)
- `Encryptor` / `Decryptor`: Class-based encryption and decryption workflows using `cryptography` (Fernet) with password-based key derivation (PBKDF2).
- `CryptoInput` / `CryptoOutput`: Normalize input data and preserve encrypted artifacts with the minimum metadata needed to restore the original payload.
- Supports strings, files, directories, and picklable Python values.

### 🖥️ System & GUI (Optional: `[gui]`)
- `monitor_keep_alive`: Prevent system sleep by simulating activity when no user input is detected.
- `MonitorActivity`: A simple class to track keyboard and mouse events.

### 🔍 Advanced Regex (`utilitz.regex`)
- A specialized framework for building complex, readable, and reusable regex patterns with built-in decoding for common types like integers, decimal numbers, currencies, and dates.

### 🗺️ Path Management (`utilitz.path`)
- `locate_project`: Easily find and set the project root directory.
- `set_source`: Dynamically manage `sys.path` entries.

## 🛠 Usage Examples

### Reading an Excel Table
```python
from utilitz.excel import read_excel_table

# Read a table from an Excel file starting from column A
# and filtering rows that match a specific pattern.
df = read_excel_table("data.xlsx", checkcol="A", patterncol=r"^\d+")
```

### Encrypting Data
```python
from utilitz.crypto import Encryptor

secret = "My secret message"
password = "strong-password"

encrypted = Encryptor.from_string(secret).encrypt(password)
token = encrypted.to_string()
original = encrypted.to_decryptor().decrypt(password).to_string()
```

### Encrypting Python Values
```python
from utilitz.crypto import Encryptor

payload = {"name": "ana", "roles": ["admin", "editor"]}
password = "strong-password"

encrypted = Encryptor.from_value(payload).encrypt(password)
restored = encrypted.to_decryptor().decrypt(password).to_value()
```

### Keeping the System Awake
```python
from utilitz.sys import monitor_keep_alive

# Press 'ctrl' every 60 seconds if no activity is detected
monitor_keep_alive(seconds=60, key='ctrl')
```

## 📄 License
This project is licensed under the **GNU General Public License v3 (GPLv3)**.
