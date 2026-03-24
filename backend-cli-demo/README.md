# backend-cli-demo — Terminal Application for ADHD Reading Companion Backend

This project is a simple terminal application that demonstrates the functionalities of the ADHD Reading Companion backend. It allows users to interact with the backend API through a command-line interface, enabling operations such as uploading documents, creating reading sessions, and checking the health of the API.

## Project Structure

```
backend-cli-demo
├── src
│   ├── main.py              # Entry point of the terminal application
│   ├── client
│   │   └── api.py           # API client for backend interactions
│   ├── commands
│   │   ├── documents.py      # Document-related commands
│   │   ├── sessions.py       # Session-related commands
│   │   └── health.py         # Health check command
│   └── types
│       └── __init__.py      # Custom types and data models
├── requirements.txt          # Project dependencies
├── .env.example              # Environment variable template
└── README.md                 # Project documentation
```

## Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Wenfei-Yuan/cs150_final_project.git
   cd cs150_final_project/backend-cli-demo
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy the `.env.example` file to `.env` and set the necessary variables, such as the API base URL.

## Usage

To run the terminal application, execute the following command:

```bash
python src/main.py
```

### Available Commands

- **Upload Document:** Upload a PDF document to the backend.
- **Create Session:** Start a new reading session.
- **Submit Retell:** Submit a retell for evaluation.
- **Advance to Next Chunk:** Move to the next chunk of the document.
- **Check Health:** Verify the health status of the backend API.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any enhancements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.