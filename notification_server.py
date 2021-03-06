from threading import Thread, Event, enumerate as list_threads
from get_candles import Coin # Self made
from glob import glob
import subprocess
import time
import json 
import sys
import re
import os


class Notification_server():
    '''
    Start server with 0 or more coin symbols to monitor, for example: 
        <python3 notification_server.py INJ RVN MONA BTC>

    When no arguments entered, server will monitor all coins stored in database, or prompt user if none are stored. 

    Enter 'commands' to view all avaliable server commands  
    '''

    SERVER_SPEED = 5 # Deafult server tick speed 5 seconds.
    REQUEST_INTERVAL = 60 # Deafult server Binance candle request interval.
    SERVER_USERS = {} # Dict keeping track of server users and their attributes (coins, update_intervals, thresholds, previlages). 
    MONITORED_COINS = {} # Dict of coins server is currently monitoring. 
    MESSAGE_BACKLOG = [] # List of messages for server_stdout() to process in order. 
    OUTGOING_MESSAGES = {} # Dict of messages from all users which get seqentially delivered to each respective user email
    BULL_THRESHOLD = 25 # Deafult thresholds before notification sent. Each user can set their own threshold under their attributes. (eventually implement ML)
    BEAR_THRESHOLD = 25 # Eventually will make both of these dicts with keys as coins, value as threshold.
    MODE_1_MESSAGES = {} # Dict to store mode 1 (signal) like messages for server_user thread to read/send.
    MODE_2_MESSAGES = {} # Dict to store mode 2 (update) like messages for server_user thread to read/send.
    MODE_2_REQUEST = 0 # Whenever a user thread requires a new update, this will handle that.
    SERVER_COMMANDS = ['commands', 'monitor', 'all', 'now', 'drop', 'monitoring', 'request_interval', 'quit', 'stdout', 'server_speed', 'notify', 'debug', 'post']
    SERVER_INSTRUCTION = {'drop': '', "stdout": 0, 'request_interval': [], 'pause': 0, 'boost': 0, 'post':0, 'new_user':''}

    tickspeed_handler = Event() # Event object to handle server tick speed. 
    server_shutdown = Event() # Event object to handle server shutdown if command 'quit' is entered.
    
    def __init__(self, coin_symbols=[]):

        self.tickspeed_handler.set()
        self.root_path = os.path.dirname(os.path.realpath(__file__))
        self.data_path = self.root_path + '/coindata'
        self.script_path = self.root_path + '/notification_scripts'
        self.attribute_path = self.script_path + '/server_attributes'
        self.postfix_init = False
        self.server_owner_gmail = ''
        if not os.path.exists(self.data_path):
            os.mkdir(self.data_path) # This acts like a database to store all users coins and anaylsis.
        self.server_welcome()

        if coin_symbols:
            self.monitor_all_coins(coins=coin_symbols) # Monitor all coins given as arguments if valid.
        else:
            self.monitor_all_coins() # Monitor all coins stored in local storage, if no coins, then prompt user input. 
   
        Thread(target=self.server_tick_speed, name='server_tick', daemon=True).start() # Global server tick speed.
        Thread(target=self.request_interval_handler, name='server_intervals', daemon=True).start() # Global server timer for sending candle requests.
        Thread(target=self.server_stdout, name='server_stdout', daemon=True).start() # Handles smooth server stdout. 
        Thread(target=self.server_user_stdinput, name='server_input', daemon=True).start() # Ready server to intake user inputs


    def server_welcome(self):
        '''Server welcome'''

        print(f'Server has been initiated!')
        print(f'Server is ready to intake commands. Type "commands" to view avaliable commands:')
        print(f'Enter command "notify" to commence server gmail notification service')
        print(f'Enter command "post" to receive your chosen coin scores and summaries\n')


    def server_commands(self):
        '''Prints description of each server command'''

        print(f'\nList of commands:')
        print('='*130)
        print(f'<commands>: Returns list of commands with description.')
        print(f'<monitor>: Allows user to add new multiple new coins, tradingpairs and timeframes to monitor.')
        print(f'<monitoring>: Server returns all coins it is currently monitoring.')
        print(f'<all>: Server will start monitoring all coins, tradingpairs and timeframes stored in the local database.')
        print(f'<drop>: Allows user to drop specific coins, tradingpairs and timeframes from monitoring or database.')
        print(f'<post>: Server will stdout the latest coin score and json.')            
        print(f'<stdout>: Toggles server stdout between periodic and OFF - server starts off in OFF state.')
        print(f'<server_speed>: Allows user to modify server tick speed.')
        print(f'<request_interval>: Allows user to modify server communication interval with Binance for candle retreival (deafult 1 minute).')
        print(f'<notify>: Starts up the server notification mailing service. If first time, this will start the initialisation process.')
        print(f'<quit>: Shuts down server activity.')
        print('='*130 + '\n')


    def server_user_stdinput(self):
        '''Thread handles user inputs'''

        while True:
            user_input = input() # Pauses thread until user input.
            if user_input in self.SERVER_COMMANDS:
                if user_input == 'commands':
                    self.server_commands()
                elif user_input == 'quit':
                    self.shutdown_server()
                elif user_input == 'post':
                    self.SERVER_INSTRUCTION['post'] = 1
                elif user_input == 'stdout':
                    self.toggle_stdout()
                elif user_input == 'request_interval':
                    self.update_timers('request_interval')
                elif user_input == 'server_speed':
                    self.update_timers('server_speed')
                elif user_input == 'monitoring':
                    self.current_monitoring()
                elif user_input == 'monitor':
                    self.input_monitor_new()
                elif user_input == 'all':
                    self.monitor_all_coins()
                elif user_input == 'drop':
                    self.input_drop_coin()
                elif user_input == 'notify':
                    self.notification_init()
                elif user_input == 'debug':
                    print(f'Server instruction settings are:\n{self.SERVER_INSTRUCTION}')
                    self.debug()
            else:
                print(f'{user_input} is an invalid server command.')
                print(f'Enter "commands" to view all avaliable commands.')


    def add_to_monitoring(self, coin_symbol=None, input_dict={}):
        '''Handles validating and adding items into the server monitoring dictionary MONITORED_COINS'''
        
        # This case is for server start up only
        if coin_symbol:
            input_dict[coin_symbol] = {'NA':[]} 

        # This section handles determining whether coin is valid with Binance, if so it will add to server monitoring.
        added_coins = set()
        for coin_symbol in input_dict:
            for tradingpair in input_dict[coin_symbol]:
                coin = Coin(coin_symbol) # Create new coin object to monitor. 
                files = coin.list_saved_files() # Used to determine whether coin exists in local storage or not.
                timeframes = input_dict[coin_symbol][tradingpair]
                deafult_timeframes = ['1w', '3d', '1d', '4h', '1h']

                if len(files) == 0:  
                    # This means coin had no local storage   
                    if tradingpair != 'NA':
                        if coin.get_candles(tradingpair=tradingpair, intervals=timeframes):
                            pass # Binance succesfully returned candles for coin-tradingpair/timeframe.
                        else:
                            print(f'{coin_symbol}{tradingpair} is not avaliable on Binance.')
                            continue # Binance rejected request.
                    elif coin.get_candles(tradingpair='USDT', intervals=deafult_timeframes):
                        tradingpair = 'USDT' # No tradingpair specified so deafult tradingpair assigned to coin.
                        print(f'\nServer will monitor {coin_symbol}USDT by deafult.')
                    else:
                        print(f'{coin_symbol} is not avaliable on Binance.')
                        continue # This means coin provided is invalid for Binance.
                elif tradingpair != 'NA':
                    # Server has local storage of coin.
                    if coin.get_candles(tradingpair=tradingpair, intervals=timeframes):
                        pass # This either added a new tradingpair or updated the existing stored one.
                    else:
                        print(f'{coin_symbol}{tradingpair} is not avaliable on Binance.')
                        continue # This means newly entered tradingpair is invalid for Binance. 
                print(f'Server will start monitoring {coin_symbol}{tradingpair}.\n') if tradingpair != 'NA' else print(f'Server will start monitoring {coin_symbol}.\n')
                added_coins.add(coin_symbol)

                # Add coin to server monitoring list
                if coin_symbol not in self.MONITORED_COINS.keys():
                    self.MONITORED_COINS[coin_symbol] = []
                files = coin.list_saved_files() # New coin csv files may have been added. 
                for csvfile_name in files:
                    symbol_timeframe = csvfile_name.split('.')[0]
                    symbol = symbol_timeframe.split('_')[0]
                    if tradingpair == 'NA' or symbol == coin.coin_symbol + tradingpair:
                        if symbol_timeframe not in self.MONITORED_COINS[coin_symbol]:
                            self.MONITORED_COINS[coin_symbol].append(symbol_timeframe) # Append only tradingpair/timeframe which server will actively monitoring.
                self.MONITORED_COINS[coin_symbol].sort()
        return added_coins # Return set of succesfully added coins. 


    def monitor_coin(self, coin_symbol):
        '''Thread starts the monitoring and score calculation of given coin. Handles external signals to drop activity'''

        coin = Coin(coin_symbol) # Create coin object.
        trim = len(coin_symbol)
        previous_bull_score = 0
        previous_bear_score = 0
        while True:
            self.tickspeed_handler.wait() # Releases every server tick.

            # Check to see whether coin drop instruction is activate.
            if self.SERVER_INSTRUCTION['drop'] and self.SERVER_INSTRUCTION['drop'][1:trim + 1] == coin_symbol:    
                item_to_drop = self.SERVER_INSTRUCTION['drop']
                self.SERVER_INSTRUCTION['drop'] = ''
                if re.search(item_to_drop.rstrip('1')[1:], str(self.MONITORED_COINS[coin_symbol])):
                    if '1' == item_to_drop[-1]:
                        item_to_drop = item_to_drop.rstrip('1')
                        if '1' == item_to_drop[0]:
                            coin.remove_coin() # Remove from database. 
                        elif '2' == item_to_drop[0]:
                            coin.remove_tradingpair(item_to_drop) # Remove from database. 
                        else:
                            coin.remove_timeframe(item_to_drop) # Remove from database. 
                    clone_MONITORED_COINS = self.MONITORED_COINS[coin_symbol].copy()
                    for pair in clone_MONITORED_COINS:
                        if item_to_drop[1:] == pair or item_to_drop[1:] in pair:
                            self.MONITORED_COINS[coin_symbol].remove(pair)
                    print(f'The following has been dropped: {item_to_drop[1:]}')
                    if '1' == item_to_drop[0] or len(self.MONITORED_COINS[coin_symbol]) == 0:
                        self.MONITORED_COINS.pop(coin_symbol)
                        return 0 # Drop this coin thread.

            # Check to see whether request timer has activated.
            if coin_symbol in self.SERVER_INSTRUCTION['request_interval']:
                self.SERVER_INSTRUCTION['request_interval'].remove(coin_symbol) # Let's request_interval thread know which coins have started scoring.
                symbol_timeframes = self.MONITORED_COINS[coin_symbol] # Only monitor specified tradingpairs.
                coin_score = coin.current_score(monitoring=symbol_timeframes) # Retreve coin score and analysis summary. 
                bull_score = coin_score[1]
                bear_score = coin_score[2]

                if re.search(coin_symbol, str(self.SERVER_INSTRUCTION['drop'])):
                    continue # If user just entered coin to drop when score already processed.
                if len(self.MESSAGE_BACKLOG) < len(self.MONITORED_COINS):
                    self.MESSAGE_BACKLOG.append(coin_score) # Send data to stdout method. 
                try:
                    if self.MODE_1_MESSAGES[coin_symbol] and not self.SERVER_INSTRUCTION['new_user']:
                        self.MODE_1_MESSAGES.pop(coin_symbol) # To prevent recuring posting of mode1 type messages.
                except KeyError:
                    pass

                if bull_score > previous_bull_score or bear_score > previous_bear_score:
                    if coin_score[1] >= self.BULL_THRESHOLD:
                        coin.generate_result_files(mode='signal') # Generate/replace signal graph/csv files in server_mail/outgoing for users to send
                        self.MODE_1_MESSAGES[coin_symbol] = f'BULL_{self.BULL_THRESHOLD}' # Send message to all users subscribed to this coin
                    elif coin_score[2] >= self.BEAR_THRESHOLD:
                        coin.generate_result_files(mode='signal')
                        self.MODE_1_MESSAGES[coin_symbol] = f'BEAR_{self.BEAR_THRESHOLD}' 

                if self.MODE_2_REQUEST:
                    coin.generate_result_files(mode='update')
                    self.MODE_2_REQUEST -= 1 # Once the value becomes zero, any user thread which is ready will send a mode 2 email.


    def current_monitoring(self, stored=False):
        '''Returns list of coins, trading pairs and timeframes server is currently monitoring'''

        coins_dict = {}
        if stored:
            for coin_path in glob(self.data_path + '/*'):
                coin = coin_path.split('/')[-1]
                coins_dict[coin] = [tradingpair.split('/')[-1][:-4] for tradingpair in glob(coin_path + f"/{coin}*")]
        else:
            coins_dict = self.MONITORED_COINS.copy()

        if coins_dict:
            if stored:
                print(f'Server has the following pairs in the database:')
            else:
                print(f'Server is currently monitoring:')
        else:
            print(f'Server has no stored or monitored coins. Enter command "monitor" to add new coins.')

        for coin in coins_dict:
            print(f'coin {coin}:')
            tradingpairs = {}
            for symbol_timeframe in coins_dict[coin]:
                tradingpair = symbol_timeframe.split('_')[0]
                timeframe = symbol_timeframe.split('_')[-1]
                try:
                    tradingpairs[tradingpair].append(timeframe)
                except KeyError:
                    tradingpairs[tradingpair] = [timeframe]
            for tradingpair in tradingpairs:
                print(tradingpair, ':', [timeframe[1:] for timeframe in sorted([Coin.INTERVALS[timeframe] + timeframe for timeframe in tradingpairs[tradingpair]])]) # Print natrually ordered timeframes
        print('')

    def monitor_all_coins(self, coins=None):
        '''Hanndles server coin monitoring initiation and 'all' command'''

        if not coins:
            paths = glob(self.data_path + '/*') 
            if len(paths) == 0:
                self.input_monitor_new() # If no coins are found in coindata directory, prompt user to enter coin.
            coins = [path.split('/')[-1] for path in paths] # Clean path to get only the directory name (i.e. coin_symbol).

        coins_to_add = set()
        for coin in coins:
            coins_to_add = coins_to_add.union(self.add_to_monitoring(coin_symbol = coin.upper())) # Validate each coin entered, add to monitoring
        self.add_new_coins(coins_to_add) # Start thread for each coin if one doesn't already exist.


    def request_interval_handler(self):
        '''Thread used to synchronise all monitor_coin method threads'''

        while True:
            threads = [str(thread).split(',')[0].split('(')[1] for thread in list_threads()] # List all activate threads.
            coins = [coin for coin in threads if coin in self.MONITORED_COINS] # List only active coin threads.
            self.SERVER_INSTRUCTION['request_interval'] = coins # Change global variable to be list of coins ready to have scores checked.
            Thread(target=self.boost_speed, args=(0.1,), daemon=True).start() # Temporarily boost server speed for faster processing. 
            while self.SERVER_INSTRUCTION['request_interval'] != []:
                self.tickspeed_handler.wait() # Keep checking every server tick whether all coin threads have starting scoring.
            self.SERVER_INSTRUCTION['boost'] = 0 # Turn off boost thread.
            time.sleep(self.REQUEST_INTERVAL) # Releases every request_interval time. 


    def server_tick_speed(self):
        '''Thread server speed, every SERVER_SPEED time elapsed will release the tickspeed_handler object'''
        
        while True:
            self.tickspeed_handler.set() # Releases the event object for all active threads from waiting. 
            self.tickspeed_handler.wait() # Just a small measure to ensure all server .wait() methods are reached.
            self.tickspeed_handler.clear() # Locks server wide event object. 
            time.sleep(self.SERVER_SPEED)


    def server_stdout(self):
        '''Thread handles server stdout (so that thread stdouts don't overlap)'''

        messages = []
        while True:
            self.tickspeed_handler.wait() # Releases every server tick.
            if len(self.MESSAGE_BACKLOG) >= len(self.MONITORED_COINS):
                messages = self.MESSAGE_BACKLOG.copy()
                self.MESSAGE_BACKLOG = [] # Empty message log.
                if self.SERVER_INSTRUCTION['stdout']:
                    self.SERVER_INSTRUCTION['post'] = 1 # Note, post can be turned on via user input also. 

            if self.SERVER_INSTRUCTION['post']:
                while True:
                    if self.SERVER_INSTRUCTION['pause']:
                        time.sleep(1)
                        continue
                    break
                for message in messages:
                    if message[-1] == 'coin_score':
                        print('\n\n' + '='*130)
                        print(f'\nCoin {message[0]} monitoring update:')
                        print(f'Overview:')
                        print(json.dumps(message[3], indent=4))
                        print(f'Bull score: {message[1]} out of 60')
                        print(f'Bear score: {message[2]} out of 60')
                        print('='*130 + '\n\n')
                self.SERVER_INSTRUCTION['post'] = 0


    def toggle_stdout(self):
        '''Toggles server stdout between periodic and prompt only'''

        if self.SERVER_INSTRUCTION['stdout'] == 1:
            print('Server stdout has been toggled OFF.')
            self.SERVER_INSTRUCTION['stdout'] = 0
        else:
            print('Server stdout has been toggled ON.')
            self.SERVER_INSTRUCTION['stdout'] = 1

    
    def update_timers(self, timer):
        '''Handles updating server clocks'''

        words = []
        if timer == 'request_interval':
            words.extend([' (minute)', 'request_interval'])
        elif timer == 'server_speed':
            words.extend([' (second)', 'tick speed'])

        self.SERVER_INSTRUCTION['pause'] = 1
        user_input = input(f'Please input a positive integer{words[0]} for new server {words[1]}: ')
        self.SERVER_INSTRUCTION['pause'] = 0
        try:
            user_input = int(user_input)
            if user_input > 0:
                print(f'Server {words[1]} updated to {user_input}{words[0]}.') 
                if timer == 'request_interval':
                    self.REQUEST_INTERVAL = user_input * 60
                elif timer == 'server_speed':
                    self.SERVER_SPEED = user_input
                return 1
        except ValueError:
            pass
        print(f'{user_input} is an invalid entry. Please input a positive integer.')

    def boost_speed(self, boost):
        '''Thread which toggles server speed from normal to responsive'''

        original_SERVER_SPEED = self.SERVER_SPEED
        self.SERVER_SPEED = boost
        self.SERVER_INSTRUCTION['boost'] = boost
        while self.SERVER_INSTRUCTION['boost']:
            time.sleep(boost)
        self.SERVER_SPEED = original_SERVER_SPEED

    
    def input_monitor_new(self):
        '''Handles user input for specifying multiple new coins, trading pairs or timeframes to monitor by the server'''

        input_coin_dict = {}
        deafult_timeframes = ['1w', '3d', '1d', '4h', '1h']

        self.SERVER_INSTRUCTION['pause'] = 1 # Stops all server stdout for cleaner user interaction.
        self.current_monitoring()
        self.current_monitoring(stored=True)
        print('='*10 + 'INSTRUCTIONS' + '='*10)
        print('>>> If multiple, seperate by spaces')
        print('>>> Enter coin(s) to monitor, choose their respective tradingpair(s) and Optionally list their timeframe(s)')
        print(f'>>> If no tradingpairs are entered, deafult timeframes will be used: {deafult_timeframes}')
           
        while True:
            coin_symbols = str(input('Input coins: ')).upper() # TODO Make this also handle mail requests 
            if len(coin_symbols) == 0:
                continue
            if self.re_search(coin_symbols):
                continue
            break
        for coin_symbol in coin_symbols.split(' '):
            if coin_symbol == '':
                continue
            input_coin_dict[coin_symbol] = {} # Dictionary for tradingpairs.

        for coin_symbol in input_coin_dict:
            while True:
                tradingpairs = str(input(f'Input {coin_symbol} trading pairs: ')).upper() 
                if self.re_search(tradingpairs):
                    continue
                break
            tradingpairs = tradingpairs.split(' ')
            for tradingpair in tradingpairs:
                if tradingpair == '':
                    continue
                input_coin_dict[coin_symbol][tradingpair] = [] # List for timeframes of each tradingpair.
            for tradingpair in input_coin_dict[coin_symbol]:
                symbol = coin_symbol + tradingpair
                try:
                    for monitored_symbol_timeframe in self.MONITORED_COINS[coin_symbol]:
                        if symbol == monitored_symbol_timeframe.split('_')[0]:
                            input_coin_dict[coin_symbol][tradingpair].append(monitored_symbol_timeframe.split('_')[1]) # Add all monitored timeframes for a given tradingpair.
                except KeyError:
                    pass # Means server is not monitoring coin.

                if input_coin_dict[coin_symbol][tradingpair]:
                    # This means coin is currently being monitored by server. User can add aditional trading pairs or timeframes.
                    print(f'Server currently monitoring {coin_symbol + tradingpair} with timeframes: {input_coin_dict[coin_symbol][tradingpair]}')
                else:
                    # This means coin entered is currently not being monitored by server (although it could be in the database). 
                    inspect_coin = Coin(coin_symbol) 
                    stored_timeframes = inspect_coin.get_timeframes(coin_symbol + tradingpair)
                    if stored_timeframes:
                        # This means server is not currently monitoring this tradingpair, however has its timeframes stored in database.
                        print(f'Server will start monitoring {coin_symbol + tradingpair} with stored timeframes: {stored_timeframes}')   
                        input_coin_dict[coin_symbol][tradingpair] = stored_timeframes   
                    else:
                        # This means server does not have any timeframes of this coin/trading pair stored. Deafult timeframes will be monitored.
                        print(f'Server will start monitoring {coin_symbol + tradingpair} with deafult timeframes: {deafult_timeframes}')
                        input_coin_dict[coin_symbol][tradingpair] = deafult_timeframes.copy()

                while True:
                    timeframes = input('OPTIONAL: Input additional timeframes: ') # White spaces will be handled in Coin.get_candles(). 
                    if self.re_search(timeframes):
                        continue
                    input_coin_dict[coin_symbol][tradingpair].extend(timeframes.split(' ')) # Add any additional timeframes on top of current ones. 
                    break
        
        self.SERVER_INSTRUCTION['pause'] = 0 # Unpause server stdout.
        added_coins = self.add_to_monitoring(input_dict=input_coin_dict) # Verify all user entries and add them to monitoring.
        Thread(target=self.add_new_coins, args=(added_coins,), daemon=True).start() # Input all successful entries.


    def add_new_coins(self, added_coins):
        '''Handles creating new coin threads if they are currently not being monitored by server'''

        for coin_symbol in added_coins:
            if not [thread for thread in list_threads() if str(thread).split(',')[0].split('(')[1] == coin_symbol]:
                # Means server is not currently monitoring this coin, so start new thread. 
                Thread(target=self.monitor_coin, name=coin_symbol, args=(coin_symbol,), daemon=True).start()

    
    def input_drop_coin(self):
        '''Handles user input for dropping a coin, tradingpair or timeframe from being monitored and removes from database if requested'''

        input_coin_dict = {}
        to_drop = set()
        
        self.SERVER_INSTRUCTION['pause'] = 1 # Stops all server stdout for cleaner user interaction.
        self.current_monitoring()
        self.current_monitoring(stored=True)
        print('Enter a coins, coins/tradingpairs, or coins/tradingpairs/timeframes to drop in the list above, appending "-drop"s')
        print('='*10 + 'INSTRUCTIONS' + '='*10)
        print('>>> If multiple, seperate by spaces')
        print('>>> To drop all related pairs of a given entry, append "-drop" (e.g. INJ-drop drops all INJ pairs, INJBTC-drop drops all INJBTC pairs)')
        print('>>> To drop given entry from server database aswell, append "1" to "-drop" (e.g. INJ-drop1, INJBTC-drop1, RVNUSDT_6h1)')
        while True:
            coin_symbols = str(input('Input coins: ')).upper()
            if len(coin_symbols) == 0:
                continue
            if self.re_search(coin_symbols):
                continue
            break
        for coin_symbol in coin_symbols.split(' '):
            if coin_symbol == '':
                continue
            input_coin_dict[coin_symbol] = [] # List for tradingpairs.

        for coin_symbol in input_coin_dict:
            if '-DROP' in coin_symbol:
                to_drop.add(coin_symbol)
                continue # Skip rest of user input interaction. 
            while True:
                tradingpairs = str(input(f'Input {coin_symbol} trading pairs: ')).upper() 
                if self.re_search(tradingpairs):
                    continue
                tradingpairs = tradingpairs.split(' ')
                for tradingpair in tradingpairs:
                    if tradingpair == '':
                        continue
                    if '-DROP' in tradingpair:
                        to_drop.add(coin_symbol + '_' + tradingpair)
                        continue # Skip rest of user input interaction. 
                    input_coin_dict[coin_symbol].append(tradingpair) 
                break

            for tradingpair in input_coin_dict[coin_symbol]:
                while True:
                    timeframes = str(input(f'Input {coin_symbol + tradingpair} timeframes: '))
                    if self.re_search(timeframes):
                        continue
                    if not re.search('[^ ]', timeframes):
                        to_drop.add(coin_symbol + '_' + tradingpair) # This means the user just entered a white space.
                    for timeframe in timeframes.split(' '):
                        timeframe = timeframe.replace('-drop', '') # Incase user appended -drop, which is not needed.
                        if timeframe == '' or len(timeframe) > 4 or timeframe[-1] in '023456789':
                            continue # Remove impossible entries immediately.
                        if timeframe == '1m':
                            timeframe = '1M' # 1M month is the only timeframe with uppercase. 1m is for 1 minute however that should never be used. 
                        to_drop.add(coin_symbol + '_' + tradingpair + '_@' + timeframe)  
                    break
        Thread(target=self.drop_coins, args=(to_drop,), daemon=True).start()
        self.SERVER_INSTRUCTION['pause'] = 0 # Unpause server stdout.

    def drop_coins(self, to_drop):
        '''Handles removing given coin/tradingpair/timeframe from Server monitoring or database'''

        Thread(target=self.boost_speed, args=(0.5,), daemon=True).start() # Temporarily boost server speed for faster processing. 
        for item in to_drop:
            item = item.replace('-DROP', '')
            item = item.split('_')
            print(f'SERVER drop self.SERVER_INSTRUCTION will be {item}') #TODO remove
            if len(item) == 1:
                self.SERVER_INSTRUCTION['drop'] = '1' + item[0]
                while self.SERVER_INSTRUCTION['drop']:
                    self.tickspeed_handler.wait()
            elif len(item) == 2:
                self.SERVER_INSTRUCTION['drop'] = '2' + item[0] + item[1]
                while self.SERVER_INSTRUCTION['drop']:
                    self.tickspeed_handler.wait()
            else:
                self.SERVER_INSTRUCTION['drop'] = '3' + item[0] + item[1] + item[2].replace('@', '_')
                while self.SERVER_INSTRUCTION['drop']:
                    self.tickspeed_handler.wait()
        self.SERVER_INSTRUCTION['boost'] = 0 # Turn off boost thread.

 
    @staticmethod
    def re_search(string):
        '''Performs search for invalid symbols'''
        if re.search('[,.|!~`@#$%^&*():;/_=+\[\]\{\}]', string):
            print(f'Invalid characters used in {string}.')
            return 1
        if re.search('-', string):
            if not re.search('-drop', string, re.IGNORECASE):
                print(f'Invalid characters used in {string}.')
                return 1


    def server_user(self, gmail, owner=False):
        '''Creates user. Each thread will handles one user. Each thread can create two modes of messages to be sent to the user via email.

        Mode 0 are periodic update messages (which can be toggled off). These messages contain score, metrics, summaries and graphs.

        Mode 1 are signalling messages, when one of the users coins have passed a certain threshold.

        Each user can tune into or drop coins to receive mail from relative to them, but also send requests to the server to monitor brand new ones
        
        '''
        Previous_scores = {}
        username = gmail.split('@')[0]
        if owner:
            coins = list(self.MONITORED_COINS.keys())
            self.SERVER_USERS[gmail] = {'username':username, 'gmail':gmail, 'privilege': 'admin', 'coins':coins, 'threshold':'ML', 'update_interval': 1}
        else:
            self.SERVER_USERS[gmail] = {'username':username, 'gmail':gmail, 'privilege': 'user', 'coins':[], 'threshold':'ML', 'update_interval': 1}
        for coin in self.SERVER_USERS[gmail]['coins']:
            Previous_scores[coin] = 0 

        Thread(target=self.server_user_mode_2_message_handler, name=f'server_user_message_handler_{username}', args=(self.SERVER_USERS[gmail],), daemon=True).start()

        while True:
            if self.MODE_1_MESSAGES: # Checks for any signals (due to a coin passing their threshold) - Note, these messages get cleared elsewhere above.
                coins = self.MODE_1_MESSAGES.copy()
                for coin in coins:
                    score = coins[coin].split('_')[-1] 
                    mood = coins[coin].split('_')[0]
                    user_thresold = self.SERVER_USERS[gmail]['threshold']
                    if coin in self.SERVER_USERS[gmail]['coins'] and (user_thresold == 'ML' or score >= user_thresold):
                        if score < Previous_scores[coin]:
                            continue 
                        subject = f'SIGNAL ALERT: {coin} passed {mood}ish threshold!'
                        details = (f'{subject} SCORE: {score}#These events are rare and usually a good time to perform a swing trade.#'
                                    'The summary excel and historical score vs performance graphs have been attached to assist in your descision.')
                        files = ','.join(glob(self.root_path + f'/server_mail/outgoing/{coin}_SIGNAL*'))
                        message = {'user':gmail, 'title':subject, 'details':details, 'files':files}
                        self.OUTGOING_MESSAGES[username] = message # Send mode1 email.
            
            try:
                message = self.MODE_2_MESSAGES[gmail]
                self.OUTGOING_MESSAGES[gmail] = message # send mode2 email.
                self.MODE_2_MESSAGES.pop(gmail)
            except KeyError:
                pass # After each users specified interval passes, their new mode2 message will become avaliable.
            
            self.tickspeed_handler.wait()


    def server_user_mode_2_message_handler(self, user_dict={}):
        '''Each user has a thread of this which waits for their specific update_interval before sending a mode 2 message'''

        # Thread will send mode 2 message upon creation, and then wait for update_interval time to send next one. 
        while True:
            self.MODE_2_REQUEST = len(self.MONITORED_COINS)
            while self.MODE_2_REQUEST:
                self.tickspeed_handler.wait()
            update_message_timer = user_dict['update_interval'] * 3600 # seconds.
            gmail = user_dict['gmail']
            coins = user_dict['coins']
            subject = f'UPDATE for coins {coins}'
            details = (f'This is a periodic update email containing csv and graph data on your monitored coins.#'
                        f'Your coins are: {coins}#'
                        f'The next update will send in {update_message_timer/3600} hours.#'
                        'To scilence this type of message, email this address the command "silence".#' 
                        'To modify how often this type of message sends, email this address "update-X"')
            files = ','.join([','.join(file_group) for file_group in [glob(self.root_path + f'/server_mail/outgoing/{coin}_UPDATE*') for coin in coins] if file_group != []])
            message = {'user':gmail, 'title':subject, 'details':details, 'files':files}
            self.MODE_2_MESSAGES[gmail] = message
            
            time.sleep(update_message_timer) # If user decides to increase this frequency, destroy the thread and create new one
            #TODO For a situation where a new user joins, and the mode1 messages are passed thesholds, let this create a mode1 message just as their first message


    def server_user_attributes(self, coins):
        '''Handles adding or removing attributes to the SERVER_USERS global variable'''

        #TODO potentially make a user class, with these methods, and attributes, in a seperate file - maybe 

        pass


    def recieve_mail_instructions(self):
        '''Thread which handles listening for emails from server users'''
        # Ideally waits in while loop, checking incoming mail each time (which come from script, generates new file for each mail) - by running recevie_mail.sh 
        # Once this checks the file, it deletes it (clearing inbox)
        # This will read the incoming.txt (where the received instructions are) and make/modify each outgoing.txt which then gets picked up by notification_send_gmail

        while self.postfix_init:
            self.tickspeed_handler.wait()

            # commands:
            # new_user: creates a new server_user thread
            # drop: Requires user + coin/tradingpair
            # monitor: requires user + coins etc.
            # update: requires interval
            # Silence: Stops server from sending mode 2 messages
            # request_coin: non-admin users can request a coin, which the server will store and present to the owner 
        # Instructions like: Add new user, monitor new coin, drop coin, send update, change notification etc. 


    def notification_settings(self):
        '''By deafult, server will determine the notification sensistivity based on the historical graph, this method handles the modulation of this sensititity'''

        # Also allow user to set whether the server can send a message once an 1hour just as a summery, with a different subject title in order to avoid phone buzz
        if self.postfix_init:
            pass 
        else:
            print(f'Please run the "notify" command before trying to modify notifcation settings')


    def notification_send_gmail(self):
        '''Thread which handles sending emails to server users'''

        while self.postfix_init:
            while self.OUTGOING_MESSAGES:
                to_send = self.OUTGOING_MESSAGES.copy()
                print(f'self.OUTGOING_MESSAGES is: {self.OUTGOING_MESSAGES}')
                self.tickspeed_handler.wait()
                for user in to_send:
                    self.OUTGOING_MESSAGES.pop(user)
                    message = to_send[user]
                    sendmail_process = subprocess.run([self.script_path + '/send_mail.sh', *[message[header] for header in message]])
                    if sendmail_process.returncode == 0:
                        continue
                    else:
                        print(f'Error: message for {user} did not send, script returned exit {sendmail_process.returncode}.')
            self.tickspeed_handler.wait()


    def notification_init(self):
        '''Handles postfix initiation and SMTP communication with user gmail'''

        if not self.postfix_init:
            self.SERVER_INSTRUCTION['pause'] = 1 # Stops all server stdout for cleaner user interaction.
            notification_init_process = subprocess.run(['sudo', self.script_path + '/notification_init.sh'])
            if notification_init_process.returncode == 0:
                postfix_init_process = subprocess.run(['sudo', self.script_path + '/postfix_init.sh'])
                while True:
                    if postfix_init_process.returncode == 0:
                        print("Postfix server setup completed. Notifications service will now commence!")
                        self.postfix_init = True
                        owner = True
                        with open(self.attribute_path + '/postfix.txt') as users:
                            first_line = users.readline()
                            self.server_owner_gmail = first_line.split(':')[1]
                            gmail = first_line.split(':')[-1][:-1]
                        Thread(target=self.server_user, name='server_user_owner',args=(gmail, owner), daemon=True).start() 
                        Thread(target=self.notification_send_gmail, name='notification_send_gmail', daemon=True).start()
                        Thread(target=self.recieve_mail_instructions, name='recieve_mail_instructions', daemon=True).start()
                        break 
                    elif postfix_init_process.returncode == 1:
                        print("Server notification service will NOT commence. To retry, run 'notify' command again.")
                        break
                    elif postfix_init_process.returncode == 2:
                        postfix_init_process = subprocess.run(['sudo', self.script_path + '/postfix_init.sh'])
                    time.sleep(0.5)
                self.SERVER_INSTRUCTION['pause'] = 0 # Unpause server stdout.
                return
            print("Server notification service will NOT commence until this issue is resolved.")


    def debug(self):
        '''Helper method which returns all coin threads currently running on the server'''

        print('\nServer is currently running the following threads:\n')
        [print('Thread: ' + str(thread).split(',')[0].split('(')[1]) for thread in list_threads()]
        print(f'\nServer instructions are set as: \n{self.SERVER_INSTRUCTION}')
        print(f'Server tick speed: {self.SERVER_SPEED}')
        print(f'Server interval speed: {self.REQUEST_INTERVAL}')


    def shutdown_server(self):
        '''When keyword >quit< is receieved, server will shutdown'''

        print('Server is shutting down...')
        shutdown = subprocess.run(['sudo', self.script_path + '/shutdown.sh'])
        if shutdown.returncode == 0:
            self.server_shutdown.set() # Set event object flag as ON.
        else:
            print('WARNING: server shutdown process was NOT sucessful. Please wait for the admin.')
        
        #TODO remove all incoming/outgoing files


if __name__ == '__main__':
    # Server can be started with <python3 notification_server.py>
    # Optional coin_symbols can be added, example: <python3 notification_server.py BTC LTC ETH INJ>
    # Once the server is running, to view commands enter <commands> 
    user_start_arguments = sys.argv
    if len(user_start_arguments) == 1:
        server = Notification_server()
    elif len(user_start_arguments) > 1:
        coins = user_start_arguments[1:]
        server = Notification_server(coin_symbols=coins)
    server.server_shutdown.wait() # Pauses main thread until shutdown_server method is invoked.
    print("Server shut down.")
# Main thread ends here. 