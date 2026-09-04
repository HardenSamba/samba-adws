"""The failure that leaves a disabled account behind, reported as exactly that.

Creating a usable account is three exchanges, and a refusal at the second or
third leaves an object in the directory: created, disabled, with or without a
password. That is a different outcome from "nothing happened", and telling the
two apart is the difference between an administrator finishing the job and
starting it again — or worse, creating a second object beside the first.

So a failure after the create is not the write client's own error passed
through. It is this, carrying the refusal unchanged and the account as it was
left. `reached` says which step succeeded last, which is what decides whether
the next attempt starts from the password or from the enable.
"""

from samba_adws._account import Account
from samba_adws.errors import ADWSClientError


# A refusal after the create, with the disabled account it left behind.
class AccountLeftDisabled(ADWSClientError):
    account: Account

    # Keeps the server's code and reason, and names the object as the target.
    def __init__(self, cause: ADWSClientError, account: Account) -> None:
        super().__init__(
            f"{cause.message} (the account exists, disabled; reached: {account.reached})",
            cause.code, account.dn)
        self.account = account
