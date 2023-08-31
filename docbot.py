import requests as req
import configparser
import json
import shutil
import asyncio
from datetime import datetime

#load data from config file
config = configparser.ConfigParser()
config.read('./config.ini', encoding='utf-8')
path =     str(config['SYNOLOGY']['Folder']).strip("'")
token =    str(config['TELEGRAM']['Token']).strip("'")
tapi =     str(config['TELEGRAM']['APIServer']).strip("'")
private =  bool(str(config['TELEGRAM']['isPrivate']).strip("'"))

q = asyncio.Queue() #main queue to be handled
upload_q = list() #queue to get file
download_q = dict() #queue to send file
with open('./json/answers.json', 'r', encoding='utf-8') as input: #dictionary with text answers
    say = json.load(input)

#returns ddmm string
def getdate():
    current = datetime.now()
    day = current.day
    month = current.month
    if day < 10:
        day = '0'+str(day)
    else:
        day = str(day)
    if month < 10:
        month = '0'+str(month)
    else:
        month = str(month)
    date = day+month
    return date

#generates id: ddmm-index (the index is intraday)
def createid():
    index = 1
    with open('./json/documents.json', 'r', encoding='utf-8') as input:
        iddict = json.load(input)
    input.close()
    if len(iddict) != 0:
        last_id = str(list(iddict.keys())[-1])
        if last_id != '':
                if last_id.partition('-')[0] == getdate():
                    if iddict[last_id] == '':
                        index = last_id.partition('-')[2]
                    else:
                        index = int(last_id.partition('-')[2])+1
    id = getdate()+'-'+str(index)
    iddict[id] = ''
    with open('./json/documents.json', 'w', encoding='utf-8') as output:  
        json.dump(iddict, output)
    output.close()
    return id

#getting updates from Telegram Bot API
async def getupdates(offset=0):
    response = req.get(f'{tapi}/bot{token}/getUpdates?offset={offset}').json()
    await asyncio.sleep(0.01)
    return response['result']

#sending messages to user
async def send(message, chat_id):
    req.get(f'{tapi}/bot{token}/sendMessage?chat_id={chat_id}&text={message}')
    await asyncio.sleep(0.01)

#sending document to user
async def uploadfile(message):
    chat_id = message['chat']['id']
    inner_id = message['text']

    with open('./json/documents.json', 'r', encoding='utf-8') as input:
        iddict = json.load(input)
    input.close()
    if inner_id in iddict:
        file_name = f'{iddict[inner_id]}'
        try:    #trying to open file
            document = open(f'{path}/{iddict[inner_id]}', 'rb')
        except IOError: #if failed to open file
            text = say['failed to open']
            await send(text, chat_id)
        else:   #if file opened succesfuly
            with document:
                files = {'document': (file_name, document.read())}
            response = req.post(f'{tapi}/bot{token}/sendDocument?chat_id={chat_id}', files = files).json()

            if not (response['ok']):
                text = say['something wrong']
                await send(text, chat_id)
    else:
        text = say['file not exist']
        await send(text, chat_id)

#getting document from user
async def downloadfile(file_id: str, file_name: str, chat_id: str):
    response = req.get(f'{tapi}/bot{token}/getFile?file_id={file_id}').json()
    print(response)
    file_path = response['result']['file_path']
    if response['ok']:
        response = req.get(f'{tapi}/file/bot{token}/{file_path}', stream = True)
        with open(f'{path}/{file_name}', 'wb') as out_file:
            shutil.copyfileobj(response.raw, out_file)
        with open('./json/documents.json', 'r', encoding='utf-8') as input:
            iddict = json.load(input)
        input.close()
        inner_id = download_q[chat_id]
        iddict[inner_id] = f'{file_name}'
        with open('./json/documents.json', 'w', encoding='utf-8') as output:    
            json.dump(iddict, output)
        output.close()
        text = say['succes']
        await send(text, chat_id)    
    else:
        text = say['something wrong']
        await send(text, chat_id)

#checking that the user has access
def authentication(message):
    if private:
        with open('./json/users.json', 'r', encoding='utf-8') as input:
            users = json.load(input)
        input.close()
        if message['from']['username'] in users:
            return True
        else:
            return False
    else: 
        return True

#handle incoming commands
async def commandhandler(message):
    chat_id = message['chat']['id']
    #put user in queue to send file
    if message['text'] == '/newdoc':
        inner_id = createid()
        text = say['id assigned']+f'{str(inner_id)}\n'+say['request document']
        await send(text, chat_id)
        global download_q
        download_q[chat_id] = inner_id
    #put user in queue to get file
    elif message['text'] == '/request':
        text = say['request id']
        await send(text, chat_id)
        global upload_q
        upload_q.append(chat_id)
    elif message['text'] == '/start':
        text = say['greetings']
        await send(text, chat_id)   
    else:
        text = say['unknown command']
        await send(text, chat_id)

#respond depending on the user's message
async def respond(message, case: str, update_id = 0):
    chat_id = message['chat']['id']
    #calling commands handler
    if case == 'command':
        await commandhandler(message)
    #initiate downloading file from user
    elif case == 'file':
        file_name = message['document']['file_name']
        file_id = message['document']['file_id']
        await downloadfile(file_id, file_name, chat_id)
    #initiate uploadinf file to user
    elif case == 'id':
        global upload_q
        await uploadfile(message)
    #nothing from above    
    else: 
        return

#checking the content in the incoming messages
async def read(update):
    global upload_q
    global download_q
    update_id = update['update_id']
    message = update['message']
    chat_id = message['chat']['id']
    #if there are command
    if 'entities' in message:
        if message['entities'][0]['type'] == 'bot_command':
            await respond(message, 'command', update_id)
    #if there are document and the user is in queue to send file
    elif 'document' in message and chat_id in download_q:
        await respond(message, 'file')
        download_q = [i for i in download_q if i != chat_id]
    #if there are document id and the user is in queue to get file   
    elif 'text' in message and chat_id in upload_q:
        await respond(message, 'id')
        upload_q = [i for i in upload_q if i != chat_id]
    #nothing of the above  
    else: 
        print("didn't read lol")

#get updates with messages and put it in main queue
async def recieve():
    global q
    update_id = 0

    while True:
        updates = await getupdates(update_id)
        for update in updates:
            update_id = update['update_id'] + 1
            print(update)
            q.put_nowait(update) #putting the message in queue           

#handle messages in main queue
async def handle(currents: int):
    global q
    for _ in range(currents): 
        while True:
            update = await q.get()
            if authentication(update['message']):
                await read(update)
            else:
                text = say['no acces']
                chat_id = update['message']['chat']['id']
                await send(text, chat_id)

#launch
def run():
    loop = asyncio.get_event_loop()

    try:
        print('initiated')
        loop.create_task(recieve())
        loop.create_task(handle(2))
        loop.run_forever()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    run()