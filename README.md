# pr-statistics-report
A cronjob getting statistics of open pull requests and send them to reviewers

# build
docker build -t pr_statistics:v1.0 .


# run
1.set env

~~~bash
access_token: the access_token of gitee
host: the mta prot of sender email
port: the mta prot of sender email
user: the mta username of sender email
pwd:  the mta password of sender email
from: the sender email
~~~

2.run

docker run -dit --name pr_statistics pr_statistics:v1.0

