import streamlit as st
import snowflake.connector
import spacy

# Load spaCy model
nlp = spacy.load("en_core_web_sm")

# Function to connect to Snowflake
def connect_to_snowflake():
    conn = snowflake.connector.connect(
        user=st.secrets["snowflake"]["user"],
        password=st.secrets["snowflake"]["password"],
        account=st.secrets["snowflake"]["account"],
        warehouse=st.secrets["snowflake"]["warehouse"],
        database=st.secrets["snowflake"]["database"],
        schema=st.secrets["snowflake"]["schema"]
    )
    return conn

# Function to execute a query and return results
def execute_query(conn, query):
    cursor = conn.cursor()
    cursor.execute(query)
    results = cursor.fetchall()
    columns = [col[0] for col in cursor.description]  # Get column names
    cursor.close()
    return results, columns

# Function to fetch metadata
def fetch_metadata(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = CURRENT_SCHEMA()")
    tables = [row[0] for row in cursor.fetchall()]

    metadata = {}
    for table in tables:
        cursor.execute(f"""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table}'
        """)
        columns = cursor.fetchall()
        metadata[table] = {"columns": columns}

    cursor.execute("""
        SELECT 
            fk.TABLE_NAME AS foreign_table,
            fk.COLUMN_NAME AS foreign_column,
            pk.TABLE_NAME AS primary_table,
            pk.COLUMN_NAME AS primary_column
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS fk ON tc.CONSTRAINT_NAME = fk.CONSTRAINT_NAME
        JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS rc ON tc.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS pk ON rc.UNIQUE_CONSTRAINT_NAME = pk.CONSTRAINT_NAME
        WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
    """)
    foreign_keys = cursor.fetchall()

    for fk in foreign_keys:
        foreign_table, foreign_column, primary_table, primary_column = fk
        if foreign_table in metadata:
            metadata[foreign_table]["foreign_keys"] = metadata[foreign_table].get("foreign_keys", []) + [
                (foreign_column, primary_table, primary_column)
            ]

    cursor.close()
    return metadata

# Function to extract intent and entities
def extract_intent_and_entities(user_question):
    doc = nlp(user_question)
    entities = {ent.text.lower(): ent.label_ for ent in doc.ents}
    intent = None

    if "count" in user_question.lower():
        intent = "count"
    elif "sum" in user_question.lower():
        intent = "sum"
    elif "list" in user_question.lower() or "show" in user_question.lower():
        intent = "list"
    elif "join" in user_question.lower():
        intent = "join"

    return intent, entities

# Function to generate complex queries
def generate_complex_query(metadata, intent, entities):
    tables = list(metadata.keys())
    selected_tables = [table for table in tables if table.lower() in entities.values()]
    query = None

    if intent == "count":
        query = f"SELECT COUNT(*) FROM {selected_tables[0]}"
    elif intent == "sum":
        for table in selected_tables:
            columns = metadata[table]["columns"]
            for column, _ in columns:
                if column.lower() in entities:
                    query = f"SELECT SUM({column}) FROM {table}"
                    break
    elif intent == "list":
        columns = []
        for table in selected_tables:
            columns.extend([f"{table}.{col[0]}" for col in metadata[table]["columns"]])
        query = f"SELECT {', '.join(columns)} FROM {selected_tables[0]}"
    elif intent == "join":
        if len(selected_tables) >= 2:
            table1, table2 = selected_tables[:2]
            fk_info = metadata[table1].get("foreign_keys", [])
            for fk in fk_info:
                if fk[1] == table2:
                    query = f"""
                        SELECT *
                        FROM {table1}
                        JOIN {table2} ON {table1}.{fk[0]} = {table2}.{fk[2]}
                    """
                    break

    return query

# Streamlit App
def main():
    st.title("Snowflake Query Chatbot")
    st.write("Ask a question about your data, and I'll fetch the results from Snowflake!")

    # User input
    user_question = st.text_input("Enter your question:")

    if user_question:
        # Connect to Snowflake
        conn = connect_to_snowflake()

        # Fetch metadata
        metadata = fetch_metadata(conn)

        # Extract intent and entities
        intent, entities = extract_intent_and_entities(user_question)

        # Generate SQL query
        query = generate_complex_query(metadata, intent, entities)

        if query:
            st.write(f"Generated SQL Query: `{query}`")

            # Execute the query
            results, columns = execute_query(conn, query)
            conn.close()

            # Display results
            if results:
                st.write("Query Results:")
                st.table(results)
            else:
                st.write("No results found.")
        else:
            st.write("Sorry, I couldn't generate a query for your question.")

# Run the app
if __name__ == "__main__":
    main()
