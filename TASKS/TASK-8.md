1. надо текущую структуру страницы изменить
- Tables теперь это вклвдка, справа от нее надо добавить вкладки "Users", "Text Logs"; вкладки пока пустые.
- боковая панель справа, должна быть связана только с таблицей на вкладке Tables, возможно получится как встроить эту панель во вкладку Tables
2. Вкладка "Text Logs": давай добавим возможность анализа текстовч
```
примерный вывод таблицы такой:
```
+-----------+-------+--------------------+--------------------------+------+
|thread_name|level  |message_example     |max_time                  |cnt   |
+-----------+-------+--------------------+--------------------------+------+
|MergeMutate|Error  |Exception while exec|2026-02-24 16:42:43.743222|673754|
|MergeMutate|Error  |Part /data/clickhous|2026-02-24 16:42:43.742098|336877|
|MergeMutate|Error  |Code: 40. DB::Except|2026-02-24 16:42:43.708108|13414 |
|Fetch      |Error  |auto DB::StorageRepl|2026-02-24 16:42:43.658432|716488|
|Fetch      |Error  |Part /data/clickhous|2026-02-24 16:42:43.657484|716488|
|TCPHandler |Error  |Code: 70. DB::Except|2026-02-24 16:40:01.379620|236   |
|TCPHandler |Error  |Code: 101. DB::Excep|2026-02-24 12:51:22.486249|288   |
|TCPHandler |Error  |Code: 516. DB::Excep|2026-02-24 12:24:48.546430|16    |
|HTTPHandler|Error  |Code: 194. DB::Excep|2026-02-24 12:24:38.492008|4     |
|TCPHandler |Error  |Code: 60. DB::Except|2026-02-20 16:07:01.419675|10    |
|HTTPHandler|Error  |Code: 47. DB::Except|2026-02-20 16:03:51.461197|2     |
|BgSchPool  |Warning|Cannot resolve host |2026-02-20 14:57:04.456087|2     |
|HTTPHandler|Error  |Code: 215. DB::Excep|2026-02-20 14:48:28.822081|2     |
|MergeMutate|Error  |Exception is in merg|2026-02-20 07:48:57.387136|6     |
+-----------+-------+--------------------+--------------------------+------+
```
далее, при нажитии на значение в колонке "thread_name", надо выводить боковую панель с детализацией, в которой по выбранной thread_name выводить результат запроса 
```
select event_time_microseconds,
       thread_name,
       level,
       query_id,
       logger_name,
       message
from system.text_log
where event_time_microseconds > today() - interval 2 week
  and thread_name = {{filter}}
order by event_time_microseconds desc
limit 200;
```
при этом список колонок для вывода надо иметь возможность выбирать, то есть задать такие кнопки в горизонтальном блоке с названиями колонок, по умолчанию они все нажаты, а если отжимаешь кнопку, то соответствующая колонка исчезает из вывода, и кнопка "thread_name" должна быть по умолчанию отжата
