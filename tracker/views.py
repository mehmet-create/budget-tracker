def charts():
    transactions = []
    total_income = 0
    total_expenses = 0

    # Load all transactions into the list (pseudo-code)
    for transaction in load_transactions():
        transactions.append(transaction)
        if transaction['type'] == 'income':
            total_income += transaction['amount']
        elif transaction['type'] == 'expense':
            total_expenses += transaction['amount']

    return {
        'total_income': total_income,
        'total_expenses': total_expenses,
        'transactions': transactions
    }