# AIGuessr

### 1. Подготовка

* Получите бесплатный API ключ в [Google AI Studio](https://aistudio.google.com/api-keys/).

* Установите необходимые библиотеки, открыв терминал и введя:

      pip install pillow requests


## GUI

### 2. Настройка и запуск

* Запустите скрипт:

      python main.py


* В открывшемся окне программы найдите текстовое поле «API KEY» и вставьте туда свой скопированный ключ.

* Нажмите кнопку capture и выберите область экрана с игрой.

* Нажмите analyze и подождите 10-15 секунд.

* Ответ получен!

## CLI

### 1. Чтобы войти в режим CLI, запустите скрипт с параметром --cli.

### 2. Аргументы:
  >  python geoguessr_helper.py --cli                  # CLI режим

  >  python geoguessr_helper.py --cli --capture        # CLI с кулдауном в 3 секунды заместо вручного нажатия Enter

  >  python geoguessr_helper.py --cli --key AIzaSy...  # CLI с ключом

  >  python geoguessr_helper.py --cli --key AIzaSy... --capture --bbox 0,0,1280,720 # CLI с выбранной зоной скриншота и ключом


# Credits

* Идея и оригинальный репозиторий - [delle](https://github.com/dellexe0)
