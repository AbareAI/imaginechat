from datetime import datetime
import random
import asyncio
import threading
import secrets
from urllib.parse import quote

from flask import Flask, render_template, request
from pywebio.platform.flask import webio_view
from pywebio import start_server, config
from pywebio.input import *
from pywebio.output import *
import pywebio.session
import pywebio
import openai
import pywebio.pin as pin
import time
import logging

openai.api_key = "API-KEY-HERE"


LOG_FILE_NAME = "service.log"
logging.basicConfig(
    level=logging.DEBUG,
    filename=LOG_FILE_NAME,
    filemode="a+",
    format="%(asctime)s [%(levelname)8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


PROMPT_HEADER = ""

app = Flask(__name__)
app.config.from_object(__name__)


class ChatEntry:
    def __init__(self, name: str, msg: str, timestamp: datetime):
        self.name = name
        self.msg = msg
        self.timestamp = timestamp
        
def get_prompt_header(context: str):
    return f"""The following is an ongoing chat between characters from {context}.\n\n"""
        
def text_completion(history: list, responder_name: str):
    prompt = PROMPT_HEADER
    
    for chat_entry in history:
        prompt += f"{chat_entry.name}: {chat_entry.msg}\n"
        
    prompt += f"{responder_name}: "
    response = openai.Completion.create(model="text-davinci-003", prompt="", temperature=1.0, max_tokens=50)
    return response


def get_list_of_characters(
    context: str,
):
    # # for testing purposes
    # if context == 'seinfeld':
    #     return ['Jerry', 'Elaine']
    
    messages = [
        {"role": "system", "content": 
            "Generate lists of characters."},
        {"role": "user", "content": 
            f"Return the top potential characters from {context}. Respond with just a sequential list of their names, separated by semi colons. No other text before or after."},
    ]

    gpt_response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
        max_tokens=100,
        request_timeout=60,
        temperature=1.0,
    )

    answers = []
    for choice in gpt_response.choices:
        answers.append(str(choice["message"]["content"]))
    
    character_list = answers[0]
    
    return [c.strip() for c in character_list.split(";")]

def chat_completion(
    system_msg: str,
    history: list
):
    messages = [
        {"role": "system", "content": system_msg},
    ]

    for chat_entry in history:
        messages.append({"role": "user", "content": f"{chat_entry.name}: {chat_entry.msg}"})

    gpt_response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
        max_tokens=50,
        request_timeout=60,
        temperature=1.0,
    )

    answers = []
    for choice in gpt_response.choices:
        answers.append(str(choice["message"]["content"]))
    return answers[0]

class GroupChatUser:
    def __init__(self, name):
        self.name = name


class GroupChat:
    def __init__(self, unique_id: str, context_setting: str):
        self.history = []
        self.users = []
        self.unique_id = unique_id
        self.context_setting = context_setting
        
    def add_user(self, user):
        self.users.append(user)
        
    def receive_msg(self, user_name: str, msg: str):
        put_text(f"{user_name}: {msg}", scope='msg-box')
        self.history.append(ChatEntry(user_name, msg, datetime.now()))
        
        for bot in self.users:
            names = bot.name.split()
            print(f"{names=}")
            if any(name in msg for name in names): # if this character was directly named in last msg, respond first
                print(f"mentioned {bot.name}")
                response = bot.respond(self.history)
                self.history.append(ChatEntry(bot.name, response, datetime.now()))
                print(f"{response}")
                put_text(f"{response}", scope='msg-box')
        
        self.gen_responses()

    def gen_responses(self, probability=None):
        probability = 1.0 / len(self.users) # each user has an equal chance of responding        
        someone_responded = False
        while not someone_responded:
            for bot in self.users:
                if random.random() < probability: 
                    response = bot.respond(self.history)
                    self.history.append(ChatEntry(bot.name, response, datetime.now()))
                    print(f"{response}")
                    put_text(f"{response}", scope='msg-box')
                    someone_responded = True


    def save_history_to_file(self):
        try:
            with open(f"/home/systest/groupchat/static/{self.unique_id}.html", "w") as f:
                for chat_entry in self.history:
                    f.write(f"{chat_entry.name}: {chat_entry.msg}<br/>\n")
        except Exception:
            print("failed to save history to file")
        
        tweetMessage = "I just chatted with my {} favorite characters using https://imaginenchat.abareai.com/\n\nCheckout my conversation https://imaginenchat.abareai.com/static/{}.html\n\n#ImagineNChat @AbareSmartBot #GPT".format(self.context_setting, self.unique_id)
        tweetMessage = quote(tweetMessage)

        twitter_link = 'https://twitter.com/intent/tweet?text={}'.format(tweetMessage)

        popup('Your chat was saved', [
            put_markdown('Your chat was saved. You can see it at [this link](/static/{}.html).'.format(self.unique_id)),
            put_html('<a href="{}" target="_blank">Tweet about it</a>'.format(twitter_link))
        ])

class GroupChatBot:
    def __init__(self, name: str, context: str):
        self.system_message = f"""
            Your name is {name}.
            You will respond only as {name} from {context}. 
            Each message you send will be exactly as this character.
            Do not add anything beyond your own response.
        """
        self.name = name
    
    def respond(self, msg_history: list):
        # return text_completion(msg_history, self.name)
        return chat_completion(self.system_message, msg_history)

@config(theme='dark')
def group_chat():
    pywebio.session.set_env(title='Imagine Chat', output_animation=False)
    
    context_setting, characters, user_name = gather_user_inputs()
    
    # test mode
    #context_setting = 'seinfeld'; characters = ['Jerry', 'Elaine']; user_name = 'Jerry'
    
    unique_id = secrets.token_hex(6)
    chat = GroupChat(unique_id, context_setting)
    logging.info("New Group Chat created with id: %s\t%s", context_setting, unique_id)


    put_html('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">')
    clear()
    put_row([
        put_markdown(f"# {context_setting.upper()} GROUP CHAT\n\n").style('text-align: center'),
        put_button('Share', onclick=chat.save_history_to_file, small=True),
    ], size='90%').style('align-items: center; justify-content: space-between')

    # t = threading.Thread(target=chat.chat_loop)
    # pywebio.session.register_thread(t)

    put_scrollable(put_scope('msg-box'), height=300, keep_bottom=True, style={'overflow': 'auto'})
    put_markdown("💬 Group Chat starting...\n", scope='msg-box')
    
    put_text(f"📢 {user_name} has joined the chat.", scope='msg-box')

    chat.history.append(ChatEntry("", f"📢 {user_name} has joined the chat.", datetime.now()))

    for character in characters:
        if character != user_name:
            bot = GroupChatBot(character, context_setting)
            chat.add_user(bot)
            text = f"📢 {character} has joined the chat."
            put_text(text, scope='msg-box')
            chat.history.append(ChatEntry("", text, datetime.now()))

    while True:
        chat_input = input(f"{user_name}: ")
        chat.receive_msg(user_name, chat_input)

def gather_user_inputs():
    put_markdown("# Welcome to Imagine Chat\n\n").style('text-align: center')
    put_text("Role play as your favorite characters from your favorite shows!").style('text-align: center') 

    context_setting = input(
        "To start, just choose a context for your chat group.",
        placeholder="Try the name of a TV show or a Movie."
        )
    
    clear()
    put_markdown(f"# {context_setting.upper()} GROUP CHAT\n\n").style('text-align: center')

    # Generate list of characters with GPT and let user pick and choose from a list
    suggested_characters = get_list_of_characters(context_setting)
    print(suggested_characters)
    
    selected = checkbox('Suggested Charaters', options=suggested_characters)
    
    print(selected)
    
    characters = selected
        
    user_name = select("And now pick the character you'll be playing", options=characters)
    
    return context_setting, characters, user_name
    


app.add_url_rule('/groupchat', 'webio_view', webio_view(group_chat),
            methods=['GET', 'POST', 'OPTIONS'])


@app.route("/")
def index():
    logging.info("client ip address: %s", request.remote_addr)
    return render_template("index.html")


if __name__ == "__main__":
    # Start the server
    #start_server(group_chat, port=36535, debug=True)
    app.run(debug=True, port=4000)
