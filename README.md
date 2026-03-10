# 🇯🇵 NihongoChat

**NihongoChat** is an AI chat web app for Korean learners of Japanese.  
Practice Japanese naturally as if you’re chatting with a real Japanese friend!  

---

## ✨ Features

### 🗣️ Chat with an AI Japanese Friend
- Natural Japanese conversation powered by **GPT5 mini**  
- Experience realistic chatting with a Japanese friend  
- Grammar mistakes are corrected naturally  

### 📚 Personalized Learning
- **Difficulty Levels**: Beginner, Intermediate, Advanced  
- **Topics**: Daily life, travel, food, culture, business, anime, etc.  
- **Customizable AI friend name**  

### 📖 Learning Tools
- **Korean Translation**: Click AI messages to see Korean translations  
- **Furigana**: Displays kanji readings  
- Toggle options available  

---

## 🛠️ Tech Stack
- **Backend**: FastAPI (Python)  
- **Frontend**: HTML, CSS, JavaScript  
- **AI Model**: OpenAI GPT-4o-mini  
- **Storage**: Browser LocalStorage  

---

## 📱 Getting Started

### Requirements
- Python 3.9+  
- OpenAI API key  

### Installation
```bash
# Install dependencies
cd /path/to/Japanese
pip install -r requirements.txt

# Run the server
python main.py

# Or using uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
