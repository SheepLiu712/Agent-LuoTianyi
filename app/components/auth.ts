class userAuth {
    username: string
    message_token: string

    constructor(username: string, message_token: string) {
        this.username = username
        this.message_token = message_token
    }
}

export const auth = new userAuth("", "")