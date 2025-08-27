# DatCure
DatCure is "that cure" to my data curation woes. Right now it is only an older text-to-image build, but I am working on a build for multi-modal datasets and robust text/chatbot dataset curation & generation. 

#**DISCLAIMER AND WARNING**: This is a personal tool I made using LLMS (Claude, Gemini, GPT) to assist with my personal research in training text-to-image models. It is stable for my own use cases, but it is not production-hardened. Please keep backups of your datasets in case of errors.

----------------------------------------------------

<details>
<summary>More descrtiption here.</summary>

This program takes a directory of images and displays them while cataloging comma-separated tags in any associated .txt files with the same name. If a .txt file doesn't exist for the image, one will be created in the directory at the time of adding a tag.

One of the biggest issues with balancing datasets for AI is that you have to balance several different dimensions (like color, size, number, camera angle, lighting, style, race, class, outfit, materials, or whatever you need for your use-case). The problem is that you can't sort your dataset in any way in file explorer that allows you to see everything and quickly work with a particular dimension. 

DatCure fixes this issue by allowing you to filter by tags so you can hone in on the particular dimenson of the dataset without having to hunt through a fragmented mess or having to bloat up all of your concept folders with duplicated that lead to secret overfitting. 

</details>

----------------------------------------------------

***Main Layout and Functionalities.***

<img width="4720" height="2800" alt="DatCure_01" src="https://github.com/user-attachments/assets/5df619ce-2331-4fbe-abf7-4fa93b01ad3a" />

----------------------------------------------------

<details>
<summary>How to install and run.</summary>

1.  **Create & Activate the Virtual Environment**

    First, run this command in your terminal to create the environment folder:
    ```bash
    python -m venv .venv
    ```
    Next, you need to activate it. The command depends on your operating system:

    * **On Windows:**
        ```powershell
        .venv\Scripts\activate
        ```
    * **On macOS / Linux:**
        ```bash
        source .venv/bin/activate
        ```

2.  **Install Dependencies**

    With your virtual environment active, install PyQt5:
    ```bash
    pip install PyQt5
    ```

3.  **Run the Application**

    You're all set. Launch the program with:
    ```bash
    python datcure.py

</details>

----------------------------------------------------

<details>
<summary>Loading a directory into the Gallery.</summary>

<img width="4720" height="2800" alt="DatCure_02" src="https://github.com/user-attachments/assets/0f950169-2936-4e6e-a2f3-915b1b5c3275" />

</details>

----------------------------------------------------

<details>
<summary>Adjusting the size of Thumbnails in the Gallery.</summary>

<img width="4720" height="2800" alt="DatCure_03" src="https://github.com/user-attachments/assets/fcf0d290-0f73-4fc9-b3ef-718b26e0954f" />

</details>

----------------------------------------------------

<details>
<summary>Selection Behavior.</summary>

<img width="4720" height="2800" alt="DatCure_04" src="https://github.com/user-attachments/assets/18c029c1-3617-48fc-9125-f4003bf80ffe" />

</details>

----------------------------------------------------

<details>
<summary>Filtering Behavior.</summary>

<img width="4720" height="2800" alt="DatCure_05" src="https://github.com/user-attachments/assets/c7912e99-c7f0-4231-9fa2-7927e2e593a5" />

</details>

----------------------------------------------------

<details>
<summary>Exporting Options.</summary>

<img width="4720" height="2800" alt="DatCure_06" src="https://github.com/user-attachments/assets/40462404-7b8f-4ec5-9112-4a3a98e691b8" />

</details>

----------------------------------------------------


