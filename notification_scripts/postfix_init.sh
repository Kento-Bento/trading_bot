#!/bin/sh

# Exit 0 means continue python notify function
# Exit 1 means exit python notify function
# Exit 2 means re-run python notify function

self_dir=$(dirname "$0") 

trap 'cat "${self_dir}"/server_attributes/postfix_main_original.cf > /etc/postfix/main.cf;exit 1' INT TERM  # Revert postfix main.cf to original if abrupt end.

if which postfix > /dev/null
then
    cat /etc/postfix/main.cf > "${self_dir}"/server_attributes/postfix_main_original.cf
    sed -i -re 's/^(Shutdown status:).*/\1 none/' "${self_dir}"/server_attributes/shutdown_status.txt
    service postfix status > /dev/null
    if test $? -eq 0
        echo "\nWarning: A Postfix server instance is already running. Is it okay to restart postfix?"
        echo -n 'Restart postfix server (y/n): '
        then while read response
        do 
            case "$response" in
            [Yy]|[Yy]es )
                            service postfix stop >/dev/null
                            break ;;
            [Nn]|[Nn]o  ) 
                            exit 1 ;;
            *|""        )
                            echo "Invalid response, please enter either 'y' or 'n'"
                            echo -n 'Restart postfix server (y/n): '  
            esac
        done < /dev/stdin
    elif test $? -eq 3
        then :
    fi
    sed -i -re 's/^smtp_tls_security_level=.*//g' /etc/postfix/main.cf
    name=$(hostname -f)
    domain=$(hostname -f | sed -r 's/[^\.]*\.//')
    if grep -E -w -q "^myhostname =\s*${name}" /etc/postfix/main.cf 
    then :
    else
        sed -i -re "s/^(myhostname =).*/\1 ${name}/" /etc/postfix/main.cf 
    fi
    if grep -E -w -q "^mydestination = localhost\.${domain}, , localhost" /etc/postfix/main.cf 
        then :
    else
        sed -i -re "s/^(mydestination =).*/\1 localhost.${domain}, , localhost/" /etc/postfix/main.cf
    fi
    sed -i -re 's/(relayhost =).*/\1 [smtp.gmail.com]:587/' /etc/postfix/main.cf
    if test $(grep -E '###tradingbot modification applied###' /etc/postfix/main.cf | wc -l) -ge 2
    then :
    else
        cat >> /etc/postfix/main.cf << eof

###tradingbot modification applied###
# Enables SASL authentication for postfix
smtp_sasl_auth_enable = yes
# Disallow methods that allow anonymous authentication
smtp_sasl_security_options = noanonymous
# Location of sasl_passwd we saved
smtp_sasl_password_maps = hash:/etc/postfix/sasl/sasl_passwd_tradingbot
# Enable STARTTLS encryption for SMTP
smtp_tls_security_level = encrypt
# Location of CA certificates for TLS
smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt
# TLS parameter
smtpd_use_tls=yes
###tradingbot modification applied###
eof
    fi
    echo "Postfix configeration complete."
    if ls /etc/postfix/sasl | grep -E -q 'sasl_passwd_tradingbot.db'
    then
        gmail=$(grep -E '^SERVER OWNER gmail:' "${self_dir}"/server_attributes/postfix.txt | sed -r 's/^SERVER OWNER gmail:([^:]*):.*/\1/')
        echo "Reminder, please ensure your gmail: ${gmail} has its 'Less secure app access' ON." # Note: Would normally use xdg-open, however this was built on WSL2 (could use wsl-open)
        echo "To check, follow the link: https://myaccount.google.com/lesssecureapps"
        service postfix restart >/dev/null
        exit 0
    else
        echo "Next a brand new gmail account needs to be created to communicate with the Postfix server"
        echo -n "Please create the new gmail account, then hit enter to continue..."
        read line
        echo "\nEnter the gmails full address and password (will get hashed) bellow-"
        while true
        do
            echo -n "Enter gmail address: "
            read email
            echo -n "Enter password: "
            stty -echo
            read password1
            stty echo
            echo -n "\nConfirm password: "
            stty -echo
            read password2
            stty echo
            if test "$password1" = "$password2"
            then
                echo -n "\nTradingbot server will use gmail ${email} for notification communication, confirm? (y/n): "
                while read response
                do 
                    case "$response" in
                    [Yy]|[Yy]es )
                                    echo "[smtp.gmail.com]:587 ${email}:${password2}" | cat > /etc/postfix/sasl/sasl_passwd_tradingbot
                                    postmap /etc/postfix/sasl/sasl_passwd_tradingbot
                                    chown root:root /etc/postfix/sasl/sasl_passwd_tradingbot.db
                                    chmod 600 /etc/postfix/sasl/sasl_passwd_tradingbot.db
                                    rm /etc/postfix/sasl/sasl_passwd_tradingbot
                                    if test -e "${self_dir}"/server_attributes/postfix.txt
                                    then
                                        sed -i -re "s/^(SERVER OWNER gmail:)[^:]*(:.*)/\1"${email}"\2/" "${self_dir}"/server_attributes/postfix.txt
                                    else
                                        echo "SERVER OWNER gmail:${email}:${email}" | cat > "${self_dir}"/server_attributes/postfix.txt
                                    fi
                                    echo "Password has been hashed."
                                    echo "Postfix server will restart..."
                                    service postfix restart >/dev/null
                                    echo "\nTo finalise setup, please set your 'Less secure app access' for the specified gmail to ON"
                                    echo "Use this link to change it: https://myaccount.google.com/lesssecureapps" 
                                    echo -n "Hit Enter once completed: "
                                    read line
                                    echo -n "Finally, would you like the notifications to be sent to ${email}, or a different email? (same/diff): "
                                    while read response
                                    do
                                        case "$response" in
                                        diff        )
                                                    while true
                                                    do
                                                        echo -n "Enter email to send to:"
                                                        read email
                                                        case "$email" in
                                                        *@*   )
                                                                sed -i -re "s/^(SERVER OWNER gmail:[^:]*:).*/\1"$email"/" "${self_dir}"/server_attributes/postfix.txt
                                                                break ;;
                                                        *   )
                                                                continue
                                                        esac
                                                    done
                                                    exit 0 ;;
                                        same        )
                                                    exit 0 ;;
                                        *|""        )
                                                    echo -n "Would you like the notifications to be sent to ${email}, or a different email? (same/diff): "
                                        esac
                                    done < /dev/stdin ;;
                    [Nn]|[Nn]o  )     
                                    cat "${self_dir}"/server_attributes/postfix_main_original.cf > /etc/postfix/main.cf
                                    exit 1 ;;
                    *|""        )
                                    echo "Invalid response, please enter either 'y' or 'n'"
                                    echo -n "Tradingbot server will use gmail ${email} for notification communication, confirm? (y/n): "
                    esac
                done < /dev/stdin
            else
                echo "Passwords entered do not match. Please try again"
            fi
        done
    fi
else
    echo 'Postfix SMTP is required for this program but is not on this system.'
    echo -n 'Install postfix (y/n): '
    while read response
    do 
        case "$response" in
        [Yy]|[Yy]es )
                        echo "Installation process is about to commence."
                        echo "NOTE: After installation, a postfix window will open. Hit enter for 'Internet Site'"
                        echo "NOTE: Next, hit enter again when the next window opens (i.e. system mail name set to be deafult user domain name)"
                        echo -n "Hit enter to commence installation or ctrl + C to opt out:"
                        read line
                        apt-get install mailutils
                        cat /etc/postfix/main.cf > "${self_dir}"/server_attributes/postfix_main_original.cf
                        exit 2 ;;
        [Nn]|[Nn]o  ) 
                        echo "No postfix will be installed."
                        exit 1 ;;
        *|""        )
                        echo "Invalid response, please enter either 'y' or 'n'"
                        echo -n 'Install postfix (y/n): '
        esac
    done < /dev/stdin
fi
