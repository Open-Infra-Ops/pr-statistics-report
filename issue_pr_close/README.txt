业务需求:
    MindSpore社区的issue邮件提醒
    1.获取MindSpore社区的所有issue.排除掉"MindSpore REQ Tracking System", "MindSpore Iteration Management", "MindSpore Bug Tracking System"等项目
    2.以下两种情况提取出issue内容
        2.1.判断当前时间大于评论时间/创建时间+14天并且携带mindspore-assistant标签的issue
        2.2.判断当前时间大于评论时间/创建时间+3年的issue
    3.针对上面2.2情况进行评论
    4.发邮件提醒
